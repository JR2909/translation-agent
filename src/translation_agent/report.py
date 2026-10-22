"""Auswertung eines Laufs: Vergleichstabelle, Rundenverteilung, Textlänge, Terminologie, Determinismus."""

from __future__ import annotations

import difflib
import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

LENGTH_FINDING = 1.20  # 20 % mehr als das Original ist ein Befund


def load(out_dir: Path) -> dict[str, Any]:
    return json.loads((out_dir / "results.json").read_text(encoding="utf-8"))


def cost_usd(prompt_tokens: int, completion_tokens: int, s: dict[str, Any]) -> float:
    return (prompt_tokens * s["price_in_per_mtok"] + completion_tokens * s["price_out_per_mtok"]) / 1e6


def term_consistency(terms: list[dict[str, str]], source: str, translation: str) -> list[dict[str, Any]]:
    rows = []
    for t in terms:
        n_de = len(re.findall(t["de_pattern"], source, re.I))
        n_en = len(re.findall(t["en_pattern"], translation, re.I))
        rows.append({"de": t["de"], "en": t["en"], "n_de": n_de, "n_en": n_en,
                     "measurable": n_de >= 3,
                     "consistency": min(n_en, n_de) / n_de if n_de else None})
    return rows


def _fmt(x: float | None, digits: int = 2) -> str:
    return "–" if x is None else f"{x:.{digits}f}"


def _table(header: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


def build_report(out_dir: Path, terms_path: Path) -> str:
    data = load(out_dir)
    s = data["settings"]
    runs = data["runs"]
    cases = {c["id"]: c for c in data["cases"]}
    terms = json.loads(terms_path.read_text(encoding="utf-8"))["terms"]
    full_source = " ".join(c["text"] for c in data["cases"])
    stages = list(dict.fromkeys(r["stage"] for r in runs))
    out: list[str] = [f"# Auswertung {out_dir.name}", ""]
    out.append(f"Übersetzer: `{s['translator_model']}` · Kritiker: `{s['critic_model']}` · "
               f"temperature={s['temperature']} · seed={s['seed']} · max_rounds={s['max_rounds']} · "
               f"max_tool_calls={s['max_tool_calls']} · time_budget_s={s['time_budget_s']}")
    out.append("")
    out.append(f"Substitutionspreis: {s['price_source']}. Lokal (Ollama) fallen keine API-Kosten an; "
               "die Kosten sind die Tokenzahlen aus den Ollama-Antworten × diesem Preis.")

    # 1 · Vergleichstabelle
    out += ["", "## Vergleichstabelle je Stufe", ""]
    rows = []
    for st in stages:
        rs = [r for r in runs if r["stage"] == st]
        pt = sum(r["usage"]["prompt_tokens"] for r in rs)
        ct = sum(r["usage"]["completion_tokens"] for r in rs)
        lat = [r["duration_s"] for r in rs]
        ratios = [len(r["final"].split()) / r["source_words"] for r in rs if r["final"]]
        status = Counter(r["status"] for r in rs)
        by_rep: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for r in rs:
            by_rep[r["repeat"]].append(r)
        cons = []
        for rep_runs in by_rep.values():
            tr = " ".join(r["final"] for r in sorted(rep_runs, key=lambda r: r["case"]))
            cons += [t["consistency"] for t in term_consistency(terms, full_source, tr) if t["measurable"]]
        rows.append([
            st, len(rs), ", ".join(f"{k}: {v}" for k, v in status.items()),
            _fmt(statistics.median(lat), 1), _fmt(max(lat), 1),
            sum(r["usage"]["llm_calls"] for r in rs) / len(rs),
            sum(r["usage"]["tool_calls"] for r in rs) / len(rs),
            f"{pt:,} / {ct:,}", f"{cost_usd(pt, ct, s) / len(rs):.5f}",
            _fmt(statistics.mean(ratios)) if ratios else "–",
            _fmt(statistics.mean(cons)) if cons else "nicht messbar",
        ])
    out.append(_table(
        ["Stufe", "Läufe", "Status", "Latenz Median [s]", "Latenz max [s]", "LLM-Aufrufe/Fall",
         "Werkzeugaufrufe/Fall", "Tokens in / out (gesamt)", "Kosten/Fall [$]", "Länge EN/DE", "Terminologie-Konsistenz"],
        rows))

    # 2 · Rundenverteilung (Stufe 5)
    eo = [r for r in runs if r["stage"].startswith("5")]
    if eo:
        out += ["", "## Rundenzahl bis zum Abbruch (Stufe 5) – Verteilung", ""]
        dist = Counter(len(r["rounds"]) for r in eo)
        out.append(_table(["Runden", "Fälle", "davon bestanden", "davon Obergrenze", "davon andere Schranke"],
                          [[k, dist[k],
                            sum(1 for r in eo if len(r["rounds"]) == k and r["status"] == "bestanden"),
                            sum(1 for r in eo if len(r["rounds"]) == k and r["status"] == "obergrenze"),
                            sum(1 for r in eo if len(r["rounds"]) == k
                                and r["status"] not in ("bestanden", "obergrenze"))]
                           for k in sorted(dist)]))
        n_cap = sum(1 for r in eo if r["status"] == "obergrenze")
        n_pass = sum(1 for r in eo if r["status"] == "bestanden")
        out += ["", f"Obergrenze statt „bestanden“: **{n_cap} von {len(eo)}** Läufen "
                    f"({n_pass} bestanden). Höchste Rundenzahl: **{max(dist)}**."]

        # Kriterien, an denen die Kritik hängt
        crit = Counter()
        for r in eo:
            for rd in r["rounds"]:
                for c, v in ((rd.get("verdict") or {}).get("criteria") or {}).items():
                    if not v["bestanden"]:
                        crit[c] += 1
        out += ["", "Nicht bestandene Kriterien über alle Runden: "
                + ", ".join(f"{k}: {v}" for k, v in crit.most_common())]

        # 3 · Textlänge je Runde
        out += ["", "## Textlänge je Runde (Stufe 5)", ""]
        per_round: dict[int, list[float]] = defaultdict(list)
        for r in eo:
            for rd in r["rounds"]:
                per_round[rd["n"]].append(rd["words"] / r["source_words"])
        out.append(_table(["Runde", "n", "Länge EN/DE Mittel", "max", f"Fälle > {LENGTH_FINDING:.2f}"],
                          [[k, len(v), _fmt(statistics.mean(v)), _fmt(max(v)),
                            sum(1 for x in v if x > LENGTH_FINDING)] for k, v in sorted(per_round.items())]))
        out += ["", "Einzelverläufe (Wörter je Runde, Original in Klammern):", ""]
        for r in sorted(eo, key=lambda r: (r["case"], r["repeat"])):
            out.append(f"- {r['case']} #{r['repeat']} ({r['source_words']}): "
                       + " → ".join(str(rd["words"]) for rd in r["rounds"]) + f" · {r['status']}")

    # 4 · Terminologie je Begriff
    out += ["", "## Terminologie-Konsistenz je Begriff", "",
            "Anteil der Vorkommen im Original, die im Englischen mit dem Glossarbegriff wiedergegeben sind "
            "(alle fünf Abschnitte zusammen, je Stufe und Wiederholung)."
            " Messbar nur für Begriffe mit mindestens drei Vorkommen.", ""]
    header = ["Begriff (n im Original)"] + [f"{st} #{rep}" for st in stages
                                            for rep in sorted({r["repeat"] for r in runs})]
    trows = []
    for t in terms:
        row = [f"{t['de']} → {t['en']} ({len(re.findall(t['de_pattern'], full_source, re.I))})"]
        for st in stages:
            for rep in sorted({r["repeat"] for r in runs}):
                rs = sorted((r for r in runs if r["stage"] == st and r["repeat"] == rep), key=lambda r: r["case"])
                tr = " ".join(r["final"] for r in rs)
                c = next(x for x in term_consistency([t], full_source, tr))
                row.append(_fmt(c["consistency"]) if c["measurable"] else "nicht messbar")
        trows.append(row)
    out.append(_table(header, trows))
    n_measurable = sum(1 for t in terms if len(re.findall(t["de_pattern"], full_source, re.I)) >= 3)
    out += ["", f"Messbare Begriffe (≥ 3 Vorkommen): {n_measurable} von {len(terms)}."]

    # 5 · Determinismus
    repeats = sorted({r["repeat"] for r in runs})
    if len(repeats) >= 2:
        out += ["", f"## Determinismus (Wiederholung {repeats[0]} vs. {repeats[1]})", ""]
        drows = []
        for st in stages:
            for cid in cases:
                a = next((r for r in runs if r["stage"] == st and r["case"] == cid and r["repeat"] == repeats[0]), None)
                b = next((r for r in runs if r["stage"] == st and r["case"] == cid and r["repeat"] == repeats[1]), None)
                if not a or not b:
                    continue
                sim = difflib.SequenceMatcher(None, a["final"], b["final"]).ratio()
                drows.append([st, cid, f"{len(a['rounds'])} / {len(b['rounds'])}",
                              f"{a['status']} / {b['status']}",
                              "ja" if a["final"] == b["final"] else "nein", _fmt(sim)])
        out.append(_table(["Stufe", "Fall", "Runden", "Status", "identisch", "Ähnlichkeit"], drows))
    return "\n".join(out) + "\n"


def write_report(out_dir: Path, terms_path: Path) -> Path:
    path = out_dir / "report.md"
    path.write_text(build_report(out_dir, terms_path), encoding="utf-8")
    return path
