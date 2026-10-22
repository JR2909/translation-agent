"""Ollama-Client (/api/chat) und die gemeinsame Schnittstelle für Test-Doubles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx


@dataclass
class ChatResponse:
    message: dict[str, Any]
    prompt_tokens: int
    completion_tokens: int


class ChatClient(Protocol):
    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        format: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> ChatResponse: ...


class OllamaClient:
    def __init__(self, host: str, think: bool = False) -> None:
        self.host = host.rstrip("/")
        self.think = think
        self._http = httpx.Client()

    def chat(self, model, messages, *, tools=None, format=None, options=None, timeout=None):
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": self.think,
            "options": options or {},
        }
        if tools:
            payload["tools"] = tools
        if format:
            payload["format"] = format
        resp = self._http.post(f"{self.host}/api/chat", json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return ChatResponse(
            message=data["message"],
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
        )
