"""Schranke 4: Trajektorie protokollieren.

Eine JSONL-Zeile je Schritt: Rolle bzw. Werkzeug, Argumente, Ergebnislänge, Dauer, Tokens.
Optional zusätzlich ein vollständiger Prompt-Mitschnitt (alle Nachrichten und Antworten).
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any


class Trajectory:
    def __init__(
        self,
        path: Path | None = None,
        transcript_path: Path | None = None,
        echo: bool = False,
    ) -> None:
        self.path = path
        self.transcript_path = transcript_path
        self.echo = echo
        self.steps: list[dict[str, Any]] = []
        self.context: dict[str, Any] = {}
        self._lock = threading.Lock()

    def step(
        self,
        actor: str,
        args: dict[str, Any],
        result_len: int,
        duration_s: float,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        status: str = "ok",
    ) -> dict[str, Any]:
        row = {
            **self.context,
            "step": len(self.steps) + 1,
            "actor": actor,
            "args": args,
            "result_len": result_len,
            "duration_s": round(duration_s, 3),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "status": status,
        }
        with self._lock:
            self.steps.append(row)
            line = json.dumps(row, ensure_ascii=False)
            if self.path:
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
            if self.echo:
                print(line, file=sys.stderr)
        return row

    def transcript(self, actor: str, request: dict[str, Any], response: dict[str, Any]) -> None:
        if not self.transcript_path:
            return
        row = {**self.context, "step": len(self.steps), "actor": actor,
               "request": request, "response": response}
        with self._lock, self.transcript_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
