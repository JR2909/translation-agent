"""Gemeinsame Harness für alle Stufen: gleiche Fälle, gleiche Schranken, gleiches Protokoll."""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Settings
from .glossary import Glossary
from .limits import Budget, LimitExceeded
from .llm import ChatClient
from .runner import Runner
from .stages import STAGES, StageResult
from .trajectory import Trajectory


@dataclass
class Case:
    id: str
    title: str
    text: str

    @property
    def words(self) -> int:
        return len(self.text.split())


def load_cases(path: Path) -> list[Case]:
    """Abschnitte "## <ID> <Titel>" der Quelldatei; jeder Abschnitt ist ein eigener Fall."""
    raw = re.sub(r"<!--.*?-->", "", path.read_text(encoding="utf-8"), flags=re.S)
    cases = []
    for block in re.split(r"^## ", raw, flags=re.M)[1:]:
        head, _, body = block.partition("\n")
        cid, _, title = head.strip().partition(" ")
        cases.append(Case(cid, title, " ".join(body.split())))
    return cases


def run_case(
    client: ChatClient,
    settings: Settings,
    glossary: Glossary,
    trajectory: Trajectory,
    stage: str,
    case: Case,
    repeat: int,
) -> dict[str, Any]:
    """Eine Anfrage = ein Fall in einer Stufe, mit eigenem Zeitbudget und Werkzeugzähler."""
    trajectory.context = {"stage": stage, "case": case.id, "repeat": repeat}
    budget = Budget(settings.time_budget_s, settings.max_tool_calls)
    runner = Runner(client, settings, glossary, trajectory, budget)
    result = StageResult(stage)
    t0 = time.monotonic()
    try:
        STAGES[stage](runner, case.text, result)
    except LimitExceeded as exc:
        result.status = exc.status
        result.error = str(exc)
    except Exception as exc:  # noqa: BLE001 – ein kaputter Fall soll den Gesamtlauf nicht beenden
        result.status = "fehler"
        result.error = repr(exc)
    return {
        "stage": stage,
        "case": case.id,
        "repeat": repeat,
        "status": result.status,
        "error": result.error,
        "source_words": case.words,
        "rounds": [{**asdict(r), "words": r.words} for r in result.rounds],
        "final": result.final,
        "duration_s": round(time.monotonic() - t0, 3),
        "usage": asdict(runner.usage),
    }


def run_all(
    client: ChatClient,
    settings: Settings,
    stages: list[str],
    repeats: int,
    out_dir: Path | None = None,
    case_ids: list[str] | None = None,
) -> Path:
    out_dir = out_dir or settings.results_dir / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    cases = load_cases(settings.data_dir / "source_de.md")
    if case_ids:
        cases = [c for c in cases if c.id in case_ids]
    glossary = Glossary.load(settings.data_dir / "glossary.json")
    trajectory = Trajectory(out_dir / "trajectory.jsonl", out_dir / "transcript.jsonl", echo=True)

    runs = []
    for repeat in range(1, repeats + 1):
        for stage in stages:
            for case in cases:
                run = run_case(client, settings, glossary, trajectory, stage, case, repeat)
                runs.append(run)
                print(f"[{stage} {case.id} #{repeat}] {run['status']} "
                      f"runden={len(run['rounds'])} {run['duration_s']}s", flush=True)
                _write(out_dir, settings, cases, runs)
    return out_dir


def _write(out_dir: Path, settings: Settings, cases: list[Case], runs: list[dict[str, Any]]) -> None:
    payload = {
        "settings": {k: str(v) if isinstance(v, Path) else v for k, v in asdict(settings).items()},
        "cases": [asdict(c) | {"words": c.words} for c in cases],
        "runs": runs,
    }
    (out_dir / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
