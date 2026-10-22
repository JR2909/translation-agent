"""Die Schranken 1 und 2: Obergrenzen und Zeitbudget je Anfrage.

Schranke 3 (Idempotenz) entfällt: Das einzige Werkzeug, schlage_fachbegriff_nach, liest
nur aus einem unveränderlichen Glossar. Ein wiederholter Aufruf, etwa nach einem Timeout,
liefert dasselbe Ergebnis und verändert keinen Zustand, kann also nichts doppelt auslösen.
"""

from __future__ import annotations

import time
from typing import Callable


class LimitExceeded(Exception):
    """Basisklasse: eine Schranke hat gegriffen, die Anfrage wird abgebrochen."""

    status = "abbruch"


class ToolCallLimitExceeded(LimitExceeded):
    status = "werkzeug_obergrenze"


class TimeBudgetExceeded(LimitExceeded):
    status = "zeitbudget"


class Budget:
    """Zeitbudget und Werkzeugaufruf-Zähler für genau eine Anfrage."""

    def __init__(
        self,
        time_budget_s: float,
        max_tool_calls: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.time_budget_s = time_budget_s
        self.max_tool_calls = max_tool_calls
        self.tool_calls = 0
        self._clock = clock
        self._start = clock()

    def elapsed(self) -> float:
        return self._clock() - self._start

    def remaining(self) -> float:
        return self.time_budget_s - self.elapsed()

    def check_time(self) -> None:
        if self.remaining() <= 0:
            raise TimeBudgetExceeded(
                f"Zeitbudget von {self.time_budget_s:.1f}s überschritten ({self.elapsed():.1f}s)"
            )

    def use_tool_call(self) -> None:
        if self.tool_calls >= self.max_tool_calls:
            raise ToolCallLimitExceeded(
                f"Obergrenze von {self.max_tool_calls} Werkzeugaufrufen erreicht"
            )
        self.tool_calls += 1
