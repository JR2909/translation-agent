"""Gemeinsamer Ausführungskern aller Stufen: jeder Modell- und Werkzeugaufruf läuft hier durch.

Hier werden die Schranken durchgesetzt (Zeitbudget, Werkzeug-Obergrenze) und jeder Schritt
in die Trajektorie geschrieben.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import Settings
from .glossary import TOOL_NAME, Glossary
from .limits import Budget, TimeBudgetExceeded
from .llm import ChatClient, ChatResponse
from .trajectory import Trajectory


@dataclass
class Usage:
    llm_calls: int = 0
    tool_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    by_role: dict[str, dict[str, int]] = field(default_factory=dict)


class Runner:
    def __init__(
        self,
        client: ChatClient,
        settings: Settings,
        glossary: Glossary,
        trajectory: Trajectory,
        budget: Budget,
    ) -> None:
        self.client = client
        self.settings = settings
        self.glossary = glossary
        self.trajectory = trajectory
        self.budget = budget
        self.usage = Usage()

    def options(self) -> dict[str, Any]:
        opts: dict[str, Any] = {"temperature": self.settings.temperature, "num_ctx": self.settings.num_ctx}
        if self.settings.seed is not None:
            opts["seed"] = self.settings.seed
        return opts

    def chat(
        self,
        role: str,
        model: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        format: dict[str, Any] | None = None,
    ) -> ChatResponse:
        # Schranke 2: Zeitbudget. Vor dem Aufruf prüfen und den Aufruf selbst hart begrenzen –
        # ein hängender Aufruf wird nach Ablauf des Restbudgets verlassen, nicht abgewartet.
        self.budget.check_time()
        remaining = self.budget.remaining()
        box: dict[str, Any] = {}

        def call() -> None:
            try:
                box["resp"] = self.client.chat(model, list(messages), tools=tools, format=format,
                                               options=self.options(), timeout=remaining)
            except BaseException as exc:  # noqa: BLE001 – wird im aufrufenden Thread erneut ausgelöst
                box["exc"] = exc

        args = {"model": model, "messages": len(messages), "tools": bool(tools), "format": bool(format)}
        t0 = time.monotonic()
        worker = threading.Thread(target=call, daemon=True)
        worker.start()
        worker.join(timeout=max(remaining, 0))
        duration = time.monotonic() - t0

        if worker.is_alive():
            self.trajectory.step(role, args, 0, duration, status="zeitbudget")
            raise TimeBudgetExceeded(
                f"{role}-Aufruf nach {duration:.1f}s abgebrochen (Budget {self.budget.time_budget_s:.1f}s)"
            )
        if "exc" in box:
            if isinstance(box["exc"], (TimeoutError, httpx.TimeoutException)):
                self.trajectory.step(role, args, 0, duration, status="zeitbudget")
                raise TimeBudgetExceeded(str(box["exc"])) from box["exc"]
            self.trajectory.step(role, args, 0, duration, status=f"fehler: {box['exc']!r}")
            raise box["exc"]

        resp: ChatResponse = box["resp"]
        content = resp.message.get("content") or ""
        self.usage.llm_calls += 1
        self.usage.prompt_tokens += resp.prompt_tokens
        self.usage.completion_tokens += resp.completion_tokens
        r = self.usage.by_role.setdefault(role, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0})
        r["calls"] += 1
        r["prompt_tokens"] += resp.prompt_tokens
        r["completion_tokens"] += resp.completion_tokens
        if resp.message.get("tool_calls"):
            args["tool_calls"] = [c["function"]["name"] for c in resp.message["tool_calls"]]
        self.trajectory.step(role, args, len(content), duration, resp.prompt_tokens, resp.completion_tokens)
        self.trajectory.transcript(
            role,
            {"model": model, "messages": messages, "tools": bool(tools), "format": format},
            {"message": resp.message, "prompt_tokens": resp.prompt_tokens,
             "completion_tokens": resp.completion_tokens},
        )
        return resp

    def run_tool(self, name: str, arguments: dict[str, Any]) -> str:
        # Schranke 1b: Obergrenze der Werkzeugaufrufe je Anfrage (wirft ToolCallLimitExceeded).
        self.budget.check_time()
        self.budget.use_tool_call()
        t0 = time.monotonic()
        if name == TOOL_NAME:
            result = self.glossary.lookup(str(arguments.get("begriff", "")))
        else:
            result = f'{{"fehler": "Unbekanntes Werkzeug {name}"}}'
        self.usage.tool_calls += 1
        self.trajectory.step(name, arguments, len(result), time.monotonic() - t0)
        return result

