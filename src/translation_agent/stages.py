"""Die drei Stufen der Leiter: 1 Einzelaufruf, 2 Kette, 5 Evaluator-Optimizer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .roles import (
    CRITIC_REVISION_PROMPT,
    FIXED_REVISION_PROMPT,
    format_defects,
    run_critic,
    run_translator,
    translator_messages,
)
from .runner import Runner


@dataclass
class Round:
    n: int
    translation: str
    verdict: dict[str, Any] | None = None

    @property
    def words(self) -> int:
        return len(self.translation.split())


@dataclass
class StageResult:
    stage: str
    status: str = "laeuft"
    rounds: list[Round] = field(default_factory=list)
    error: str | None = None

    @property
    def final(self) -> str:
        return self.rounds[-1].translation if self.rounds else ""


def stage1_single(runner: Runner, source: str, result: StageResult) -> None:
    """Stufe 1: ein Prompt, eine Übersetzung. Kein Werkzeug, keine Überarbeitung – Baseline."""
    text = run_translator(runner, translator_messages(source), use_tools=False)
    result.rounds.append(Round(1, text))
    result.status = "fertig"


def stage2_chain(runner: Runner, source: str, result: StageResult) -> None:
    """Stufe 2: übersetzen → mit fester Anweisung überarbeiten. Ablauf fest verdrahtet."""
    messages = translator_messages(source)
    result.rounds.append(Round(1, run_translator(runner, messages)))
    messages.append({"role": "user", "content": FIXED_REVISION_PROMPT})
    result.rounds.append(Round(2, run_translator(runner, messages)))
    result.status = "fertig"


def stage5_evaluator_optimizer(runner: Runner, source: str, result: StageResult) -> None:
    """Stufe 5: Übersetzer + Kritiker; Schleife bis „bestanden“ oder Obergrenze.

    Wie oft die Schleife läuft, entscheidet das Kritiker-Urteil bei jedem Durchlauf neu.
    """
    max_rounds = runner.settings.max_rounds
    messages = translator_messages(source)
    translation = run_translator(runner, messages)
    for n in range(1, max_rounds + 1):
        verdict = run_critic(runner, source, translation)
        result.rounds.append(Round(n, translation, verdict.to_dict()))
        if verdict.passed:
            result.status = "bestanden"
            return
        # Schranke 1a: Obergrenze der Durchläufe – nach max_rounds Kritiken wird abgebrochen.
        if n >= max_rounds:
            result.status = "obergrenze"
            return
        messages.append({"role": "user",
                         "content": CRITIC_REVISION_PROMPT.format(maengel=format_defects(verdict))})
        translation = run_translator(runner, messages)


STAGES: dict[str, Callable[[Runner, str, StageResult], None]] = {
    "1_einzelaufruf": stage1_single,
    "2_kette": stage2_chain,
    "5_evaluator_optimizer": stage5_evaluator_optimizer,
}
