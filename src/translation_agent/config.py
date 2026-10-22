"""Konfiguration aus Umgebungsvariablen (siehe docker-compose.yml)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    ollama_host: str = "http://localhost:11434"
    translator_model: str = "qwen3:4b-instruct"
    critic_model: str = "qwen3:14b"

    # Schranken
    max_rounds: int = 4          # Obergrenze der Übersetzer-Kritiker-Durchläufe (Stufe 5)
    max_tool_calls: int = 10     # Obergrenze der Werkzeugaufrufe je Anfrage
    time_budget_s: float = 600.0  # Zeitbudget je Anfrage (= je Fall und Stufe)

    temperature: float = 0.7
    seed: int | None = None      # None = nicht deterministisch, für den Determinismus-Vergleich
    num_ctx: int = 8192
    think: bool = False          # Denkmodus von qwen3 aus: spart Tokens, Ausgabe ist nur die Übersetzung

    # Substitutionspreis: lokale Tokens bewertet mit einem veröffentlichten API-Preis (USD je 1 Mio. Tokens)
    price_in_per_mtok: float = 0.15
    price_out_per_mtok: float = 0.60
    price_source: str = "OpenAI gpt-4o-mini, Listenpreis Standard-API (0,15 $ Input / 0,60 $ Output je 1 Mio. Tokens)"

    data_dir: Path = Path("data")
    results_dir: Path = Path("results")

    @classmethod
    def from_env(cls) -> "Settings":
        seed = _env("SEED", "")
        return cls(
            ollama_host=_env("OLLAMA_HOST", cls.ollama_host),
            translator_model=_env("TRANSLATOR_MODEL", cls.translator_model),
            critic_model=_env("CRITIC_MODEL", cls.critic_model),
            max_rounds=int(_env("MAX_ROUNDS", str(cls.max_rounds))),
            max_tool_calls=int(_env("MAX_TOOL_CALLS", str(cls.max_tool_calls))),
            time_budget_s=float(_env("TIME_BUDGET_S", str(cls.time_budget_s))),
            temperature=float(_env("TEMPERATURE", str(cls.temperature))),
            seed=int(seed) if seed else None,
            num_ctx=int(_env("NUM_CTX", str(cls.num_ctx))),
            think=_env("THINK", "false").lower() in ("1", "true", "yes"),
            price_in_per_mtok=float(_env("PRICE_IN_PER_MTOK", str(cls.price_in_per_mtok))),
            price_out_per_mtok=float(_env("PRICE_OUT_PER_MTOK", str(cls.price_out_per_mtok))),
            price_source=_env("PRICE_SOURCE", cls.price_source),
            data_dir=Path(_env("DATA_DIR", str(cls.data_dir))),
            results_dir=Path(_env("RESULTS_DIR", str(cls.results_dir))),
        )
