# Agentic Workflow P6: Übersetzung als Evaluator-Optimizer

Intelligence Engineering W4DSKI_410 · DHBW Heilbronn · Lauf `results/run-01` vom 22.10.2026

## 1 Aufbau

**Text.** Auszug aus der *Grundordnung der DHBW* vom 01.10.2026 (Amtliche Bekanntmachungen Nr. 31/2026):
Präambel, § 1, § 2, § 5 Abs. 1–3, zusammen **435 Wörter**, geschnitten in **fünf Fälle** A1–A5 (76–98 Wörter,
`data/source_de.md`). Die Satzung ist neun Tage vor dem Lauf veröffentlicht worden, kann also nicht in den
Trainingsdaten der Modelle stecken. Dafür spricht auch die Ausgabe: Ohne Glossar übersetzt das Modell
„Studienakademie“ wörtlich als „study academy“.

**Modelle (lokal, Ollama, RTX 5060 Ti 16 GB).** Übersetzer `qwen3:4b-instruct`, Kritiker `qwen3:14b`,
also wie empfohlen ein kleines Modell als Übersetzer und ein größeres als Kritiker. Temperatur 0,7, kein Seed.
Die erste Wahl `qwen3:4b` (Denkmodell) war unbrauchbar: Sobald Werkzeuge im Spiel waren, schrieb es seinen
Denkprozess trotz `think: false` in die Antwort (7 762 Zeichen für 76 Wörter Quelltext). Deshalb fordern beide
Übersetzer-Prompts jetzt einen `<translation>`-Block, und nur dessen Inhalt wird weiterverwendet.

**Stufen** (`src/translation_agent/stages.py`), alle über dieselbe Harness (`harness.py`) und denselben
Ausführungskern (`runner.py`):

| Stufe | Ablauf | Wer entscheidet über den Ablauf |
|---|---|---|
| 1 Einzelaufruf | ein Prompt, eine Übersetzung, kein Werkzeug | niemand, Baseline |
| 2 Kette | übersetzen → feste Überarbeitungsanweisung (dieselben vier Kriterien als Checkliste) | der Entwickler, fest verdrahtet |
| 5 Evaluator-Optimizer | übersetzen → Kritiker → bei Mängeln überarbeiten → Kritiker … bis „bestanden“ oder `MAX_ROUNDS=4` | das Kritiker-Urteil, bei jedem Durchlauf neu |

**Kritiker** (`roles.py`). Er gibt ein JSON-Urteil per Schema ab (Ollama `format`), mit je einem Urteil für
*terminologie*, *register*, *vollstaendigkeit* und *falsche_freunde*. Bestanden ist nur, wenn alle vier bestehen.
Ein Kriterium mit gelistetem Mangel zählt als nicht bestanden, auch wenn das Modell `true` meldet. Vor dem Urteil
muss der Kritiker eine `glossar_pruefung` ausfüllen: jeden Glossarbegriff im Quelltext mit Soll- und Ist-Übersetzung.
Ohne diese Prüfliste ließ er im ersten Versuch „Study Academies“ statt „campus“ in Runde 1 durchgehen.

**Werkzeug.** `schlage_fachbegriff_nach(begriff)` gegen `data/glossary.json` (20 Einträge). Der Übersetzer bekommt
es in Stufe 2 und 5 als Ollama-Tool angeboten und entscheidet selbst, ob er es aufruft.

## 2 Die vier Schranken im Code

| # | Schranke | Code | Nachweis |
|---|---|---|---|
| 1a | Obergrenze Durchläufe | `stages.py`, `stage5_evaluator_optimizer`: `if n >= max_rounds: status = "obergrenze"` | `test_round_limit_stops_loop_when_critic_never_passes`: Kritiker besteht nie → genau 3 Kritiken, 3 Übersetzungen, Status `obergrenze` |
| 1b | Obergrenze Werkzeugaufrufe | `limits.py`, `Budget.use_tool_call` → `ToolCallLimitExceeded`; aufgerufen in `Runner.run_tool` | `test_tool_call_limit_aborts_request`: Übersetzer ruft endlos das Werkzeug → nach 4 Aufrufen Abbruch `werkzeug_obergrenze` |
| 2 | Zeitbudget je Anfrage | `Runner.chat`: Prüfung vor jedem Aufruf; der Aufruf läuft in einem Thread mit `join(timeout=Restbudget)`, ein hängender Aufruf wird verlassen | `test_time_budget_aborts_slow_call` (Aufruf schläft 2 s, Budget 0,3 s → Abbruch nach < 1 s); `test_time_budget_checked_between_calls` |
| 3 | Idempotenz | entfällt, Begründung im Docstring von `limits.py` | `test_tool_is_read_only` |
| 4 | Trajektorie | `trajectory.py`: eine JSONL-Zeile je Schritt (`actor`, `args`, `result_len`, `duration_s`, `prompt_tokens`, `completion_tokens`, `status`) | `test_trajectory_has_one_line_per_step`; Lauf: `results/run-01/trajectory.jsonl` |

**Warum Idempotenz entfällt:** `schlage_fachbegriff_nach` liest nur aus einem unveränderlichen Glossar
(`MappingProxyType`). Ein wiederholter Aufruf, etwa nach einem Timeout, liefert dasselbe Ergebnis und ändert keinen
Zustand, also gibt es keine Nebenwirkung, die doppelt eintreten könnte.

Tests: `docker compose run --rm tests` → 7 passed.
Der **vollständige Prompt-Mitschnitt** des Laufs (jede Anfrage mit allen Nachrichten und jede Antwort) liegt in
`results/run-01/transcript.jsonl`.

## 3 Ergebnisse

Je Stufe 5 Fälle × 2 Wiederholungen = 10 Läufe. Volle Auswertung: `results/run-01/report.md`.

### Vergleichstabelle

| Stufe | Status | Latenz Median / max [s] | LLM-Aufrufe je Fall | Werkzeugaufrufe je Fall | Tokens in / out (10 Läufe) | Kosten je Fall [$]* | Länge EN/DE (Wörter) | Terminologie-Konsistenz |
|---|---|---|---|---|---|---|---|---|
| 1 Einzelaufruf | 10 × fertig | 2,1 / 2,4 | 1,0 | 0,0 | 3 962 / 1 351 | 0,00014 | 1,17 | 0,41 |
| 2 Kette | 10 × fertig | 4,7 / 6,2 | 2,3 | 0,6 | 18 376 / 2 998 | 0,00046 | 1,17 | 0,82 |
| 5 Evaluator-Optimizer | 9 × bestanden, 1 × Obergrenze | 38,1 / 77,8 | 5,7 | 0,3 | 56 677 / 18 644 | 0,00197 | 1,16 | 0,92 |

\* **Substitutionspreis:** Lokal fällt keine Rechnung an. Angesetzt sind die Tokenzahlen aus den Ollama-Antworten
(`prompt_eval_count`, `eval_count`) × Listenpreis OpenAI gpt-4o-mini (0,15 $ Input / 0,60 $ Output je 1 Mio. Tokens).
Das ist eine Annahme, gewählt als veröffentlichter Preis eines kleinen API-Modells, und über `PRICE_IN_PER_MTOK` /
`PRICE_OUT_PER_MTOK` änderbar. Das Verhältnis ist aussagekräftiger als der absolute Wert: **Stufe 5 kostet ≈ 14×
Stufe 1 und ≈ 18× deren Latenz.** Die Latenz enthält bei Stufe 5 auch das Laden des 14B-Kritikers.

### Rundenzahl als Verteilung (Stufe 5)

| Runden bis Abbruch | Läufe | davon bestanden | davon Obergrenze |
|---|---|---|---|
| 1 | 0 | – | – |
| 2 | 5 | 5 | 0 |
| 3 | 3 | 3 | 0 |
| 4 | 2 | 1 | 1 |

- **Kein Fall besteht in Runde 1.** Der Kritiker mit Prüfliste findet immer mindestens einen Mangel, die Schleife läuft also tatsächlich.
- **Obergrenze statt „bestanden“: 1 von 10.** Höchster Wert: 4 Runden, beide Male A5 (§ 5, dichteste Terminologie: Planstelle, studienakademieübergreifend, Grundordnungsänderung).
- Die Kritik hängt fast nur an einem Kriterium: nicht bestanden wurden *terminologie* 18×, *falsche_freunde* 1×, *register* und *vollstaendigkeit* nie.

### Textlänge je Runde

| Runde | n | EN/DE Mittel | max | Läufe > 1,20 |
|---|---|---|---|---|
| 1 | 10 | 1,18 | 1,34 | 4 |
| 2 | 10 | 1,16 | 1,31 | 2 |
| 3 | 5 | 1,20 | 1,33 | 2 |
| 4 | 2 | 1,29 | 1,33 | 2 |

Befund mit Einschränkung: Die Reflexionsschleife **baut hier kein Füllmaterial an**. Je Fall bleibt die Länge über
die Runden gleich oder sinkt (z. B. A4: 92 → 87 → 87; A5 #1: 122 → 120 → 120 → 120). Der Anstieg in Runde 4 ist ein
Selektionseffekt, denn dort kommt nur der längste Fall A5 an. Die 20-%-Schwelle reißen schon die Einzelübersetzungen
(A5: 1,28–1,34). Das liegt an der Sprache, nicht an der Schleife: Deutsche Komposita wie
„Grundordnungsänderung“ oder „studienakademieübergreifenden“ zählen als ein Wort, im Englischen werden daraus drei
bis vier. Für DE→EN wäre deshalb das Verhältnis zur **Runde 1** der faire Maßstab, nicht das zum Original.

### Terminologie-Konsistenz

Fünf Begriffe wurden vorab festgelegt (`data/terms.json`), jeder mit mindestens drei Vorkommen im Gesamttext. Die
Metrik ist also **messbar (5 von 5)**. Gemessen wird der Anteil der Vorkommen, die über alle fünf Abschnitte mit
dem Glossarbegriff übersetzt sind:

| Begriff (Vorkommen) | Stufe 1 #1 / #2 | Stufe 2 #1 / #2 | Stufe 5 #1 / #2 |
|---|---|---|---|
| Studienakademie → campus (9) | 0,00 / 0,11 | 0,67 / 0,56 | 0,89 / 1,00 |
| Fakultätsart → faculty type (6) | 1,00 / 1,00 | 1,00 / 1,00 | 1,00 / 1,00 |
| studienakademieübergreifende Fakultät → cross-campus faculty (4) | 0,00 / 0,00 | 1,00 / 1,00 | 1,00 / 1,00 |
| Planstelle → budgeted position (3) | 0,00 / 0,00 | 1,00 / 0,00 | 0,67 / 0,67 |
| Duale Partner → dual partners (3) | 1,00 / 1,00 | 1,00 / 1,00 | 1,00 / 1,00 |

Den größten Sprung bringt bereits Stufe 2, weil das Werkzeug dort überhaupt erst angeboten wird. Stufe 5 hebt
„Studienakademie → campus“ auf fast 1,0. Bemerkenswert: **Der Übersetzer nutzt das Werkzeug kaum** (0,3 Aufrufe je
Fall in Stufe 5, 0,6 in Stufe 2). Die Terminologie kommt in Stufe 5 vor allem über die Mängelliste des Kritikers
herein, und der hat das Glossar im Prompt.

### Determinismus

Jeder Fall lief zweimal mit identischer Konfiguration (Temperatur 0,7, ohne Seed).

| Stufe | Ergebnis identisch | Ähnlichkeit (difflib) | Rundenzahl gleich | Status gleich |
|---|---|---|---|---|
| 1 | 0 / 5 | 0,75–0,96 | – | – |
| 2 | 0 / 5 | 0,60–0,99 | – | – |
| 5 | 1 / 5 (A4) | 0,72–1,00 | 4 / 5 (A3: 3 vs. 2) | 4 / 5 (A5: Obergrenze vs. bestanden) |

Nicht nur der Text, auch der **Ablauf** ist nicht deterministisch: Derselbe Fall A5 endet einmal an der Obergrenze
und einmal mit „bestanden“, A3 braucht einmal 3 und einmal 2 Runden. Bei Stufe 5 hängt die Schrittzahl am
Kritiker-Urteil, und das schwankt mit. Mit `SEED` ließe sich das pro Lauf festnageln, die Streuung zeigt aber, wie
fragil das Abbruchkriterium ist.

## 4 Kritiker-Validierung

Zehn Kritikpunkte, gestreut über Fälle und Kriterien, stehen in `results/run-01/critic_validation.csv`.

> **Offen:** Die Spalte **Eigenes Urteil** und die Übereinstimmungsquote müsst ihr selbst ausfüllen. Die Spalte
> *Vorab-Einschätzung* stammt vom Assistenten, der den Code gebaut hat, und ist kein menschliches Urteil.
> Sie dient nur als Vergleich. Urteil in der CSV als `j`/`n` eintragen, dann `docker compose run --rm agent critic-score run-01`.

| # | Fall/Runde | Kriterium | Kritikpunkt (gekürzt) | Vorab-Einschätzung | Eigenes Urteil |
|---|---|---|---|---|---|
| 1 | A5/1 | terminologie | „positions“ statt „budgeted positions“ (Planstellen) | berechtigt, Glossar | |
| 2 | A2/1 | terminologie | „supra-regional faculty councils“ statt „supra-local …“ | berechtigt, Glossar | |
| 3 | A4/1 | terminologie | „studienakademieübergreifende Fakultät“ als „organized across multiple study academies“ | **nicht berechtigt**: Im Text steht nur das Adverb „studienakademieübergreifend organisiert“, nicht der Glossarbegriff. Die „Korrektur“ zu „organized as cross-campus faculties“ verschiebt den Sinn | |
| 4 | A3/2 | terminologie | „legally competent public legal entity“ statt „public-law corporation“ | berechtigt, Glossar | |
| 5 | A1/1 | terminologie | „further education“ statt „continuing education“ | berechtigt, Glossar | |
| 6 | A5/1 | falsche_freunde | „positions“ statt „budgeted positions“ | **nicht berechtigt**: Duplikat von #1 und kein falscher Freund, falsches Kriterium | |
| 7 | A5/2 | terminologie | „position“ statt „budgeted position“ | berechtigt | |
| 8 | A5/3 | terminologie | „professor“ → „professors (female and male)“ | **nicht berechtigt**: steht nicht im Glossar, die Korrektur fügt Inhalt hinzu | |
| 9 | A5/2 | terminologie | „professors (female and male)“ sei „im Glossar verpflichtend“ | **nicht berechtigt**: halluzinierter Glossareintrag | |
| 10 | A5/1 | terminologie | „senate“ statt „Senate“ | berechtigt (geringfügig) | |

Vorab-Einschätzung: 6 von 10 berechtigt (60 %). **Eigene Übereinstimmungsquote: _offen_.**

Unabhängig von der Stichprobe zeigt der Lauf **übersehene Mängel**: Die als „bestanden“ abgenommenen Endfassungen
von Stufe 5 enthalten noch 4× „Presidium“ (falscher Freund, der als Beispiel *im Kritiker-Prompt* steht!), 2×
„fundamental regulation“ statt „constitution“ und 4× „study academy“. Der Kritiker prüft also gut, was explizit im
Glossar steht und eine Prüfliste erzwingt. Register, Vollständigkeit und falsche Freunde hat er nie beanstandet,
auch dort nicht, wo es Mängel gab. Sein „bestanden“ heißt eher „keine Glossarabweichung bemerkt“ als „gute
Übersetzung“. Liegt die eigene Übereinstimmungsquote unter 50 %, optimiert die Schleife auf ein Ziel, das niemand
gemessen hat.

## 5 Ist Runde 3 besser als Runde 1, oder nur anders?

Blindvergleich: `results/run-01/blind_pairs.md` enthält je Stufe-5-Lauf mit mindestens zwei Runden ein Paar aus
Runde 1 und Runde 3 (bzw. der letzten Runde), gemischt als A/B, ohne Rundennummer. Die Zuordnung liegt getrennt in
`blind_key.json`, die nicht vorher öffnen. Urteil `A`/`B`/`gleich` in `blind_judgement.csv` eintragen, dann
`docker compose run --rm agent blind-score run-01`.

**Ergebnis: _offen_.** Erwartung aus den Daten: Die späte Runde ist bei der Glossartreue messbar besser
(Konsistenz 0,41 → 0,92). Abseits davon ändert sich wenig: Länge stabil, Ähnlichkeit zwischen den Runden hoch,
der Kritiker bemängelt fast nur Terminologie. Wo Runde 3 einen halluzinierten Mangel „behebt“ (#8/#9), ist sie nur
anders, nicht besser.

## 6 Schriftliche Fragen

**Wer entscheidet über den Ablauf, und was folgt daraus?** In Stufe 1 und 2 steht die Zahl der Aufrufe vorher fest
(1 bzw. 2 + Werkzeug), Kosten und Latenz sind planbar (Max/Median ≈ 1,1–1,3). In Stufe 5 entscheidet der Kritiker.
Die Latenz streut stärker (22–78 s), und bei identischer Eingabe streut sogar das Abbruchsignal (A5). Die
Obergrenzen sind deshalb kein Beiwerk, sondern das Einzige, was die Kosten nach oben deckelt.

**Was bringt das Werkzeug?** Weniger als gedacht: Ein 4B-Übersetzer, der selbst entscheiden darf, schlägt selten
nach (0,3–0,6 Aufrufe je Fall). Wenn er nachschlägt, dann manchmal mehrfach denselben Begriff im selben Zug. Im
ersten Versuch mit `qwen3:4b` waren es 5× „Präsidium“, das hat die Werkzeug-Obergrenze ins Spiel gebracht. Das
Glossarwissen erreicht die Übersetzung in Stufe 5 hauptsächlich über den Kritiker.

**Wie zuverlässig ist der Judge in der Schleife?** Siehe Abschnitt 4: Er findet echte Glossarabweichungen,
erfindet aber auch Glossareinträge (#9), sortiert Mängel unter falsche Kriterien (#6) und übersieht ausgerechnet
den falschen Freund aus seinem eigenen Prompt. Weil er gleichzeitig über den Abbruch entscheidet, schlägt jeder
seiner Fehler direkt auf Kosten (unnötige Runden) oder Qualität (vorzeitiges „bestanden“) durch.

## 7 Schluss: Welche Stufe für welches Problem?

Woran wir es festmachen: Kosten-/Latenzfaktor, Terminologie-Konsistenz und Streuung des Ablaufs aus diesem Lauf.
**Stufe 1** reicht, wo es auf Sinn und nicht auf Begriffstreue ankommt (Entwurf, interne Notiz, Gisting). Sie kostet ein Vierzehntel, ist planbar,
aber terminologisch inkonsistent (0,41).
**Stufe 2** ist das beste Kosten-Nutzen-Verhältnis, wenn die Qualitätskriterien vorab bekannt und als feste
Checkliste formulierbar sind: rund 3× Kosten, doppelte Latenz, Konsistenz 0,82, feste Rundenzahl.
**Stufe 5** lohnt sich nur, wenn (a) ein verbindlicher Maßstab existiert, den ein Judge prüfen kann (hier: das
Glossar), (b) Abweichungen teuer sind, etwa bei Satzungen, Verträgen oder veröffentlichten Ordnungen, und (c) der
Judge gegen menschliche Urteile validiert ist. Hier brachte Stufe 5 die beste Konsistenz (0,92) für 14× Kosten und
18× Latenz, aber ihr „bestanden“ war nur in Bezug auf das Glossar belastbar. Wo der Judge nicht validiert ist,
kauft man mit Stufe 5 keine Qualität, sondern nur einen nicht deterministischen Ablauf.
