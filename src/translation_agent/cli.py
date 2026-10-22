"""Kommandozeile: run | report | critic-export | critic-score | blind-export | blind-score."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from .config import Settings
from .harness import run_all
from .llm import OllamaClient
from .report import write_report
from .stages import STAGES
from . import validation


def _latest(settings: Settings) -> Path:
    runs = sorted(p for p in settings.results_dir.iterdir() if (p / "results.json").exists())
    if not runs:
        raise SystemExit(f"Kein Lauf in {settings.results_dir}")
    return runs[-1]


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="translation-agent")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="Alle Stufen über alle Fälle laufen lassen")
    r.add_argument("--stages", nargs="+", default=list(STAGES), choices=list(STAGES))
    r.add_argument("--cases", nargs="+", help="nur diese Fall-IDs, z. B. A1 A3")
    r.add_argument("--repeat", type=int, default=2, help="Wiederholungen (≥ 2 für den Determinismus-Vergleich)")
    r.add_argument("--out", type=Path)
    r.add_argument("--max-rounds", type=int)
    r.add_argument("--seed", type=int)

    for name in ("report", "critic-export", "critic-score", "blind-export", "blind-score"):
        sp = sub.add_parser(name)
        sp.add_argument("run_dir", type=Path, nargs="?", help="Laufverzeichnis (Standard: neuester Lauf)")

    args = p.parse_args(argv)
    settings = Settings.from_env()
    terms = settings.data_dir / "terms.json"

    if args.cmd == "run":
        if args.max_rounds is not None:
            settings = replace(settings, max_rounds=args.max_rounds)
        if args.seed is not None:
            settings = replace(settings, seed=args.seed)
        client = OllamaClient(settings.ollama_host, think=settings.think)
        out = run_all(client, settings, args.stages, args.repeat, args.out, args.cases)
        print(f"Bericht: {write_report(out, terms)}")
        print(f"Kritikpunkte: {validation.export_critic_points(out)}")
        print(f"Blindvergleich: {validation.export_blind_pairs(out)}")
        return

    run_dir = args.run_dir or _latest(settings)
    if args.cmd == "report":
        print(write_report(run_dir, terms).read_text(encoding="utf-8"))
    elif args.cmd == "critic-export":
        print(validation.export_critic_points(run_dir))
    elif args.cmd == "critic-score":
        print(json.dumps(validation.score_critic_points(run_dir), ensure_ascii=False, indent=2))
    elif args.cmd == "blind-export":
        print(validation.export_blind_pairs(run_dir))
    elif args.cmd == "blind-score":
        print(json.dumps(validation.score_blind_pairs(run_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
