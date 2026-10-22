"""Die beiden Rollen: Übersetzer (mit Werkzeug) und Kritiker (feste Kriterien, JSON-Urteil)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .glossary import TOOL_SPEC
from .runner import Runner

CRITERIA = ("terminologie", "register", "vollstaendigkeit", "falsche_freunde")

TRANSLATOR_SYSTEM = """
rolle: Fachübersetzer für deutsches Hochschul- und Verwaltungsrecht ins Englische
aufgabe: Übersetze den deutschen Text vollständig und sinngetreu ins Englische
register: formelles Register englischsprachiger Satzungen (statutes)
verbote[3]: nichts hinzufügen,nichts weglassen,nichts erklären
glossar:
  status: verbindlich
  umfang: institutionsspezifische Fachbegriffe
  werkzeug: schlage_fachbegriff_nach
  nutzung: Du entscheidest selbst, für welche Begriffe du es brauchst
ausgabe:
  format: fertige Übersetzung zwischen <translation> und </translation>
  vorbemerkung: keine
  kommentar: keiner"""

TRANSLATE_PROMPT = "Übersetze folgenden Abschnitt ins Englische:\n\n{source}"

# Stufe 2: feste, vom Entwickler verdrahtete Überarbeitungsanweisung (kein Kritiker).
FIXED_REVISION_PROMPT = """
aufgabe: Überarbeite deine Übersetzung
vorgehen: Prüfe dabei selbst
pruefpunkte[4]{name,anforderung}:
  Terminologie,Fachbegriffe gemäß Glossar und durchgehend einheitlich
  Register,formelles Englisch englischsprachiger Satzungen
  Vollständigkeit,"jeder Satz und jede Angabe des Originals ist enthalten, nichts hinzugefügt"
  Falsche Freunde,"keine scheinbar ähnlichen, aber falschen englischen Wörter"
ausgabe:
  inhalt: ausschließlich die überarbeitete Übersetzung
  format: zwischen <translation> und </translation>"""

# Stufe 5: Überarbeitung anhand der konkreten Mängel des Kritikers.
CRITIC_REVISION_PROMPT = """kontext: Ein Fachlektor hat deine Übersetzung geprüft und folgende Mängel gefunden
{maengel}
aufgabe: Überarbeite die Übersetzung so, dass diese Mängel behoben sind
einschraenkung: Ändere nichts, was nicht bemängelt wurde
ausgabe:
  inhalt: ausschließlich die überarbeitete Übersetzung
  format: zwischen <translation> und </translation>
"""

CRITIC_SYSTEM = """rolle: strenger Fachlektor für Übersetzungen deutscher Hochschulsatzungen ins Englische
aufgabe: Prüfe die englische Übersetzung gegen den deutschen Ausgangstext nach genau vier Kriterien und gib für jedes Kriterium ein eigenes Urteil ab
kriterien[4]{{name,pruefung}}:
  terminologie,Fachbegriffe entsprechen dem verbindlichen Glossar unten und sind innerhalb des Textes einheitlich
  register,"formelles, juristisch-administratives Englisch wie in englischsprachigen Satzungen; keine Umgangssprache"
  vollstaendigkeit,"jede Aussage, Zahl, Bedingung und Aufzählung des Originals ist enthalten; nichts hinzugefügt"
  falsche_freunde,keine falschen Freunde
beispiele_falsche_freunde[5]: Gremium ≠ gremium,Präsidium ≠ presidium,Ausbildung ≠ training only,eventuell ≠ eventually,Konsequenz ≠ consequence im Sinne von Folgerichtigkeit
vorgehen[2]: "Trage zuerst in \"glossar_pruefung\" jeden Glossarbegriff ein, der im deutschen Text vorkommt (auch flektiert oder als Teil eines Kompositums), mit der verbindlichen englischen Entsprechung und der tatsächlich verwendeten Wiedergabe in der Übersetzung. Jede Abweichung ist ein Terminologie-Mangel.",Urteile erst danach über die vier Kriterien
bestanden: "Ein Kriterium ist nur bestanden, wenn du keinen Mangel findest"
mangel:
  konkret: zitiere die betroffene Stelle der Übersetzung und nenne die Korrektur
  keine_erfindung: "Erfinde keine Mängel; findest du keinen, ist die Liste leer"

glossar_verbindlich_de_en:
{glossar}"""

CRITIC_PROMPT = """Deutscher Ausgangstext:
<<<
{source}
>>>

Englische Übersetzung:
<<<
{translation}
>>>

Gib dein Urteil als JSON zurück."""

_CRITERION_SCHEMA = {
    "type": "object",
    "properties": {
        "bestanden": {"type": "boolean"},
        "maengel": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["bestanden", "maengel"],
}
CRITIC_SCHEMA = {
    "type": "object",
    "properties": {
        "glossar_pruefung": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"de": {"type": "string"}, "erwartet": {"type": "string"},
                               "verwendet": {"type": "string"}, "korrekt": {"type": "boolean"}},
                "required": ["de", "erwartet", "verwendet", "korrekt"],
            },
        },
        **{c: _CRITERION_SCHEMA for c in CRITERIA},
    },
    "required": ["glossar_pruefung", *CRITERIA],
}


@dataclass
class Verdict:
    criteria: dict[str, dict[str, Any]] = field(default_factory=dict)
    glossary_check: list[dict[str, Any]] = field(default_factory=list)
    parse_error: str | None = None

    @property
    def passed(self) -> bool:
        # Bestanden nur, wenn alle vier Kriterien bestehen.
        return self.parse_error is None and all(
            self.criteria.get(c, {}).get("bestanden") is True for c in CRITERIA
        )

    def defects(self) -> list[tuple[str, str]]:
        out = []
        for c in CRITERIA:
            entry = self.criteria.get(c, {})
            for m in entry.get("maengel", []):
                out.append((c, m))
            if entry.get("bestanden") is False and not entry.get("maengel"):
                out.append((c, "Kriterium nicht bestanden (ohne Begründung)"))
        if self.parse_error:
            out.append(("format", self.parse_error))
        return out

    def to_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "criteria": self.criteria,
                "glossary_check": self.glossary_check, "parse_error": self.parse_error}


_THINK_RE = re.compile(r"<think>.*?</think>", re.S)
_TRANSLATION_RE = re.compile(r"<translation>(.*?)(?:</translation>|$)", re.S)


def clean(text: str) -> str:
    return _THINK_RE.sub("", text).strip()


def extract_translation(text: str) -> str:
    """Nur der Inhalt des letzten <translation>-Blocks; ohne Tags der ganze Text."""
    text = clean(text)
    found = _TRANSLATION_RE.findall(text)
    return found[-1].strip() if found else text


def run_translator(runner: Runner, messages: list[dict[str, Any]], use_tools: bool = True) -> str:
    """Übersetzer-Zug inkl. Werkzeugschleife. Das Modell entscheidet, ob und wann es nachschlägt."""
    while True:
        resp = runner.chat("uebersetzer", runner.settings.translator_model, messages,
                           tools=[TOOL_SPEC] if use_tools else None)
        msg = resp.message
        messages.append({k: msg[k] for k in ("role", "content", "tool_calls") if k in msg})
        calls = msg.get("tool_calls") or []
        if not calls:
            return extract_translation(msg.get("content") or "")
        for call in calls:
            fn = call.get("function", {})
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"begriff": args}
            result = runner.run_tool(fn.get("name", ""), args)  # Obergrenze greift hier
            messages.append({"role": "tool", "tool_name": fn.get("name", ""), "content": result})


def translator_messages(source: str) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": TRANSLATOR_SYSTEM},
        {"role": "user", "content": TRANSLATE_PROMPT.format(source=source)},
    ]


def run_critic(runner: Runner, source: str, translation: str) -> Verdict:
    messages = [
        {"role": "system", "content": CRITIC_SYSTEM.format(glossar=runner.glossary.as_prompt_table())},
        {"role": "user", "content": CRITIC_PROMPT.format(source=source, translation=translation)},
    ]
    resp = runner.chat("kritiker", runner.settings.critic_model, messages, format=CRITIC_SCHEMA)
    raw = clean(resp.message.get("content") or "")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return Verdict(parse_error=f"Kritiker-Antwort ist kein JSON: {exc}")
    criteria = {}
    for c in CRITERIA:
        entry = data.get(c) or {}
        maengel = [str(m) for m in entry.get("maengel", []) if str(m).strip()]
        # Ein Kriterium mit gelistetem Mangel gilt als nicht bestanden, auch wenn das Modell "true" sagt.
        criteria[c] = {"bestanden": bool(entry.get("bestanden")) and not maengel, "maengel": maengel}
    return Verdict(criteria=criteria, glossary_check=data.get("glossar_pruefung") or [])


def format_defects(verdict: Verdict) -> str:
    return "\n".join(f"- [{c}] {m}" for c, m in verdict.defects())
