"""Das einzige Werkzeug: schlage_fachbegriff_nach(begriff) gegen ein Glossar mit 20 Einträgen."""

from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

TOOL_NAME = "schlage_fachbegriff_nach"

TOOL_SPEC: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": (
            "Schlägt die verbindliche englische Übersetzung eines deutschen Fachbegriffs "
            "der DHBW-Hochschulverwaltung im Glossar nach. Nur bei Fachbegriffen nutzen, "
            "deren Übersetzung nicht eindeutig ist."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "begriff": {"type": "string", "description": "Deutscher Fachbegriff, z. B. 'Planstelle'"}
            },
            "required": ["begriff"],
        },
    },
}


class Glossary:
    def __init__(self, entries: Mapping[str, Mapping[str, str]]) -> None:
        # Nur lesend: das Werkzeug verändert keinen Zustand (deshalb entfällt Schranke 3).
        self.entries = MappingProxyType({k: dict(v) for k, v in entries.items()})

    @classmethod
    def load(cls, path: Path) -> "Glossary":
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def lookup(self, begriff: str) -> str:
        """Ergebnis als JSON-Text für die Tool-Nachricht."""
        query = begriff.strip().casefold()
        hits = [k for k in self.entries if k.casefold() == query]
        if not hits:
            # Flexionsformen und Komposita: "Studienakademien" findet "Studienakademie"
            hits = [k for k in self.entries
                    if k.casefold() in query or (len(query) >= 5 and query in k.casefold())]
        if not hits:
            return json.dumps({"begriff": begriff, "gefunden": False,
                               "hinweis": "Kein Glossareintrag. Übersetze nach bestem Fachwissen."},
                              ensure_ascii=False)
        return json.dumps(
            {"begriff": begriff, "gefunden": True,
             "eintraege": [{"de": k, **self.entries[k]} for k in hits]},
            ensure_ascii=False,
        )

    def as_prompt_table(self) -> str:
        return "\n".join(f"- {k} → {v['en']}" for k, v in self.entries.items())
