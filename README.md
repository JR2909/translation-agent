# translation-agent

Ein Übersetzer erzeugt, ein Kritiker prüft gegen vier feste Kriterien (Terminologie, Register,
Vollständigkeit, falsche Freunde), der Übersetzer überarbeitet, bis alle vier bestehen oder die Obergrenze greift.
Lokal mit Ollama, alles läuft über `podman compose`.

## Schnellstart

Mit Podman: `systemctl --user start podman.socket`

```bash
podman-compose up -d ollama 
podman-compose run --rm pull && podman-compose run --rm agent && podman-compose run --rm tests
python -m translation_agent run
```

Die GPU wird per CDI eingebunden (`nvidia.com/gpu=all`, nvidia-container-toolkit erforderlich).
Unter SELinux setzt die Compose-Datei dafür `label=disable`.

Lokal ohne Container: `pip install -e '.[dev]'`, `OLLAMA_HOST=http://localhost:11434 python -m translation_agent run`.

## Modelle

| Rolle       | Modell                                                   | Größe                | Hinweise                                                                                  |
| ----------- | -------------------------------------------------------- | ---------------------- | ----------------------------------------------------------------------------------------- |
| Übersetzer | [`qwen3:4b-instruct`](https://ollama.com/library/qwen3) | 4B, Q4_K_M, ≈ 2,5 GB  | Nicht-Denk-Variante mit Tool-Calling; ruft `schlage_fachbegriff_nach` selbst auf        |
| Kritiker    | [`qwen3:14b`](https://ollama.com/library/qwen3)         | 14B, Q4_K_M, ≈ 9,3 GB | Gibt ein JSON-Urteil per Schema aus (Ollama `format`), Denkmodus aus (`think: false`) |

Bewusst ein kleines Modell als Übersetzer und ein größeres als Kritiker. Beide passen zusammen auf eine GPU mit
16 GB (`OLLAMA_MAX_LOADED_MODELS=2`). Verworfen wurde `qwen3:4b` als Übersetzer: Sobald Werkzeuge angeboten
werden, schreibt es seinen Denkprozess trotz `think: false` in die Antwort.

Parameter im Lauf `results/run-01`: `temperature=0.7`, kein Seed, `num_ctx=8192`. Andere Modelle lassen sich über
`TRANSLATOR_MODEL` / `CRITIC_MODEL` setzen, z. B. in einer `.env`.

## Aufbau

```
translation-agent/
├── .github/
│   └── workflows/
│       └── tests.yml
├── .pytest_cache/
├── .venv/
├── data/
├── docs/
├── results/
├── src/
│   └── translation_agent/
│       ├── __pycache__/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── config.py
│       ├── glossary.py
│       ├── harness.py
│       ├── limits.py
│       ├── llm.py
│       ├── report.py
│       ├── roles.py
│       ├── runner.py
│       ├── stages.py
│       ├── trajectory.py
│       └── validation.py
│   └── translation_agent.egg-info/
├── tests/
├── .dockerignore
├── .gitignore
├── docker-compose.yml
├── Dockerfile
├── LICENSE
├── pyproject.toml
└── README.md
```

## Ausgaben eines Laufs (`results/<lauf>/`)

- `results.json`: alle Fälle, Runden, Urteile, Tokens
- `trajectory.jsonl`: eine Zeile je Schritt (Rolle/Werkzeug, Argumente, Ergebnislänge, Dauer, Tokens)
- `transcript.jsonl`: vollständiger Prompt-Mitschnitt (jede Anfrage mit allen Nachrichten und jede Antwort)
- `report.md`: Auswertung
- `critic_validation.csv`: 10 Kritikpunkte zum eigenen Beurteilen (`j`/`n`), auswerten mit `agent critic-score`
- `blind_pairs.md`, `blind_judgement.csv`: Runde 1 vs. Runde 3 blind (`A`/`B`/`gleich`), auswerten mit `agent blind-score`

## Konfiguration

Per Umgebungsvariable in der compose: 

`TRANSLATOR_MODEL`
`CRITIC_MODEL`
`MAX_ROUNDS`
`MAX_TOOL_CALLS` (10)
`TIME_BUDGET_S` (600)
`TEMPERATURE` (0.7)
`SEED` (leer)
`NUM_CTX`
`PRICE_IN_PER_MTOK`
`PRICE_OUT_PER_MTOK`
