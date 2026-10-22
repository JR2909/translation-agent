"""Judge-Validierung: Kritikpunkte von Hand beurteilen und Runde 1 gegen Runde 3 blind vergleichen."""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path

from .report import load

CRITIC_CSV = "critic_validation.csv"
BLIND_MD = "blind_pairs.md"
BLIND_CSV = "blind_judgement.csv"
BLIND_KEY = "blind_key.json"


def export_critic_points(out_dir: Path, n: int = 10, seed: int = 7) -> Path:
    """Zieht n Kritikpunkte (über Fälle und Kriterien gestreut) in eine CSV zum Beurteilen."""
    data = load(out_dir)
    cases = {c["id"]: c["text"] for c in data["cases"]}
    points = []
    for r in data["runs"]:
        if not r["stage"].startswith("5"):
            continue
        for rd in r["rounds"]:
            for crit, v in ((rd.get("verdict") or {}).get("criteria") or {}).items():
                for m in v["maengel"]:
                    points.append({"fall": r["case"], "wiederholung": r["repeat"], "runde": rd["n"],
                                   "kriterium": crit, "mangel": m,
                                   "ausgangstext": cases[r["case"]], "uebersetzung": rd["translation"]})
    rng = random.Random(seed)
    rng.shuffle(points)
    # Streuung: erst je (Fall, Kriterium) einen Punkt, dann auffüllen
    picked, seen = [], set()
    for p in points:
        if (p["fall"], p["kriterium"]) not in seen:
            seen.add((p["fall"], p["kriterium"]))
            picked.append(p)
    picked += [p for p in points if p not in picked]
    picked = picked[:n]
    path = out_dir / CRITIC_CSV
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "fall", "wiederholung", "runde", "kriterium", "mangel",
                                          "urteil_berechtigt_j_n", "begruendung", "ausgangstext", "uebersetzung"])
        w.writeheader()
        for i, p in enumerate(picked, 1):
            w.writerow({"id": i, **p, "urteil_berechtigt_j_n": "", "begruendung": ""})
    return path


def score_critic_points(out_dir: Path) -> dict[str, object]:
    with (out_dir / CRITIC_CSV).open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    judged = [r for r in rows if r["urteil_berechtigt_j_n"].strip().lower() in ("j", "n")]
    agree = sum(1 for r in judged if r["urteil_berechtigt_j_n"].strip().lower() == "j")
    rate = agree / len(judged) if judged else None
    return {"punkte": len(rows), "beurteilt": len(judged), "berechtigt": agree,
            "uebereinstimmung": rate,
            "befund": None if rate is None else
            ("Kritiker unter 50 % – die Schleife optimiert auf ein ungemessenes Ziel" if rate < 0.5
             else "Kritiker mindestens 50 % – Urteil als Abbruchkriterium vertretbar")}


def export_blind_pairs(out_dir: Path, later_round: int = 3, seed: int = 11) -> Path:
    """Runde 1 gegen Runde `later_round` (bzw. die letzte vorhandene ≥ 2), gemischt und ohne Rundennummer."""
    data = load(out_dir)
    cases = {c["id"]: c["text"] for c in data["cases"]}
    rng = random.Random(seed)
    pairs, key = [], {}
    for r in data["runs"]:
        if not r["stage"].startswith("5") or len(r["rounds"]) < 2:
            continue
        first = r["rounds"][0]
        later = r["rounds"][min(later_round, len(r["rounds"])) - 1]
        texts = [("frueh", first), ("spaet", later)]
        rng.shuffle(texts)
        pairs.append({"fall": r["case"], "texts": texts, "src": cases[r["case"]]})
    rng.shuffle(pairs)
    md = ["# Blindvergleich", "",
          "Für jedes Paar: welche Übersetzung ist besser? In blind_judgement.csv `A`, `B` oder `gleich` eintragen.", ""]
    for i, p in enumerate(pairs, 1):
        pid = f"P{i:02d}"
        key[pid] = {"fall": p["fall"], "A": p["texts"][0][0], "B": p["texts"][1][0],
                    "runden": {"A": p["texts"][0][1]["n"], "B": p["texts"][1][1]["n"]}}
        md += [f"## {pid}", "", "**Original:**", "", p["src"], "",
               "**A:**", "", p["texts"][0][1]["translation"], "",
               "**B:**", "", p["texts"][1][1]["translation"], ""]
    (out_dir / BLIND_MD).write_text("\n".join(md), encoding="utf-8")
    (out_dir / BLIND_KEY).write_text(json.dumps(key, indent=2), encoding="utf-8")
    with (out_dir / BLIND_CSV).open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["paar", "besser_A_B_gleich"])
        for pid in key:
            w.writerow([pid, ""])
    return out_dir / BLIND_MD


def score_blind_pairs(out_dir: Path) -> dict[str, int]:
    key = json.loads((out_dir / BLIND_KEY).read_text(encoding="utf-8"))
    result = {"spaete_runde_besser": 0, "runde_1_besser": 0, "gleich": 0, "offen": 0}
    with (out_dir / BLIND_CSV).open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            choice = row["besser_A_B_gleich"].strip().upper()
            if choice in ("A", "B"):
                result["spaete_runde_besser" if key[row["paar"]][choice] == "spaet" else "runde_1_besser"] += 1
            elif choice == "GLEICH":
                result["gleich"] += 1
            else:
                result["offen"] += 1
    return result
