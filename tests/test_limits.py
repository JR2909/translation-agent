"""Tests zu den Schranken 1, 2 und 4 (und eine Prüfung der Begründung für 3)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from translation_agent.config import Settings
from translation_agent.glossary import TOOL_NAME, Glossary
from translation_agent.harness import Case, run_case
from translation_agent.llm import ChatResponse
from translation_agent.trajectory import Trajectory

DATA = Path(__file__).resolve().parents[1] / "data"
CASE = Case("T1", "Test", "Die Studienakademie hat eine Planstelle.")


class FakeClient:
    """Test-Double für Ollama: Antwort je Rolle über Funktionen, optional künstlich langsam."""

    def __init__(self, translator=None, critic=None, delay_s: float = 0.0):
        self.translator = translator or (lambda msgs: {"role": "assistant", "content": "The campus has a budgeted position."})
        self.critic = critic or (lambda msgs: {"role": "assistant", "content": _verdict(passed=True)})
        self.delay_s = delay_s
        self.calls: list[str] = []

    def chat(self, model, messages, *, tools=None, format=None, options=None, timeout=None):
        role = "critic" if format else "translator"
        self.calls.append(role)
        if self.delay_s:
            time.sleep(self.delay_s)
        msg = (self.critic if format else self.translator)(messages)
        return ChatResponse(message=msg, prompt_tokens=100, completion_tokens=20)


def _verdict(passed: bool) -> str:
    maengel = [] if passed else ["'plan position' → 'budgeted position'"]
    return json.dumps({c: {"bestanden": passed, "maengel": maengel if c == "terminologie" else []}
                       for c in ("terminologie", "register", "vollstaendigkeit", "falsche_freunde")})


def _settings(**kw) -> Settings:
    return Settings(data_dir=DATA, **kw)


def _run(client, stage="5_evaluator_optimizer", **kw):
    traj = Trajectory()
    run = run_case(client, _settings(**kw), Glossary.load(DATA / "glossary.json"), traj, stage, CASE, 1)
    return run, traj


# --- Schranke 1a: Obergrenze der Durchläufe ---------------------------------------------------

def test_round_limit_stops_loop_when_critic_never_passes():
    client = FakeClient(critic=lambda m: {"role": "assistant", "content": _verdict(passed=False)})
    run, _ = _run(client, max_rounds=3)
    assert run["status"] == "obergrenze"
    assert len(run["rounds"]) == 3
    assert client.calls.count("critic") == 3
    assert client.calls.count("translator") == 3  # Erstübersetzung + 2 Überarbeitungen, keine vierte


def test_loop_stops_early_on_pass():
    verdicts = iter([False, True])
    client = FakeClient(critic=lambda m: {"role": "assistant", "content": _verdict(next(verdicts))})
    run, _ = _run(client, max_rounds=5)
    assert run["status"] == "bestanden"
    assert len(run["rounds"]) == 2


# --- Schranke 1b: Obergrenze der Werkzeugaufrufe ----------------------------------------------

def test_tool_call_limit_aborts_request():
    looping = lambda m: {"role": "assistant", "content": "",
                         "tool_calls": [{"function": {"name": TOOL_NAME, "arguments": {"begriff": "Planstelle"}}}]}
    client = FakeClient(translator=looping)
    run, traj = _run(client, max_tool_calls=4)
    assert run["status"] == "werkzeug_obergrenze"
    assert run["usage"]["tool_calls"] == 4
    assert sum(1 for s in traj.steps if s["actor"] == TOOL_NAME) == 4


# --- Schranke 2: Zeitbudget je Anfrage --------------------------------------------------------

def test_time_budget_aborts_slow_call():
    client = FakeClient(delay_s=2.0)
    t0 = time.monotonic()
    run, traj = _run(client, time_budget_s=0.3)
    elapsed = time.monotonic() - t0
    assert run["status"] == "zeitbudget"
    assert elapsed < 1.0, "der langsame Aufruf darf nicht abgewartet werden"
    assert traj.steps[-1]["status"] == "zeitbudget"


def test_time_budget_checked_between_calls():
    client = FakeClient(delay_s=0.15,
                        critic=lambda m: {"role": "assistant", "content": _verdict(passed=False)})
    run, _ = _run(client, time_budget_s=0.5, max_rounds=10)
    assert run["status"] == "zeitbudget"
    assert 1 <= len(run["rounds"]) < 10


# --- Schranke 3: Idempotenz entfällt – Werkzeug ist rein lesend ------------------------------

def test_tool_is_read_only():
    g = Glossary.load(DATA / "glossary.json")
    before = dict(g.entries)
    assert g.lookup("Planstellen") == g.lookup("Planstellen")
    assert dict(g.entries) == before
    with pytest.raises(TypeError):
        g.entries["Planstelle"] = {"en": "x"}  # type: ignore[index]


# --- Schranke 4: Trajektorie ------------------------------------------------------------------

def test_trajectory_has_one_line_per_step(tmp_path):
    calls = iter([
        {"role": "assistant", "content": "",
         "tool_calls": [{"function": {"name": TOOL_NAME, "arguments": {"begriff": "Studienakademie"}}}]},
        {"role": "assistant", "content": "The campus has a budgeted position."},
    ])
    client = FakeClient(translator=lambda m: next(calls))
    traj = Trajectory(tmp_path / "t.jsonl")
    run_case(client, _settings(), Glossary.load(DATA / "glossary.json"), traj, "5_evaluator_optimizer", CASE, 1)
    lines = [json.loads(l) for l in (tmp_path / "t.jsonl").read_text().splitlines()]
    assert [l["actor"] for l in lines] == ["uebersetzer", TOOL_NAME, "uebersetzer", "kritiker"]
    for l in lines:
        assert {"actor", "args", "result_len", "duration_s", "prompt_tokens", "completion_tokens"} <= l.keys()
    assert lines[1]["args"] == {"begriff": "Studienakademie"}
    assert lines[0]["prompt_tokens"] == 100
