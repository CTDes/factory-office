# factory-office

One place to see what the [software factory](https://github.com/CTDes/software-factory) is doing
in every repository, on every machine.

Each factory (software-factory 0.3.0 or later) pushes its job transitions here. factory-office
stores them in SQLite and serves the latest state of every job. A pixel-art office view comes next.

```text
machine A: factory-job ──POST /events──┐
machine B: factory-job ──POST /events──┼──> factory-office ──> SQLite ──> GET /state, /events, tail
CI runner: factory-job ──POST /events──┘
```

## Run it

Python 3.10+, standard library only.

```sh
pip install -e .                       # or: PYTHONPATH=src python3 -m factory_office ...
factory-office token add my-laptop     # prints the token once
factory-office serve                   # http://127.0.0.1:8765, db in ~/.local/share/factory-office/
```

On each machine that runs the factory, set once in `~/.claude/settings.json`:

```json
{ "env": { "FACTORY_EVENTS_URL": "http://127.0.0.1:8765/events", "FACTORY_EVENTS_TOKEN": "<token>" } }
```

Then, in each repository that already has jobs, send its history once:

```sh
factory-job events backfill
```

## Look at it

```sh
factory-office state          # active jobs per repository, finished ones counted
factory-office state --all    # include done and rejected
factory-office tail -f        # every transition as it arrives, like events.log for all repos
```

## HTTP API

| Route | Auth | Answer |
| --- | --- | --- |
| `GET /health` | none | `{"ok": true}` |
| `POST /events` | token | body `{"events": [...]}`; `{"accepted": n, "duplicates": m}` |
| `GET /state` | token | `{"repos": [...], "jobs": [...]}`, each job with its latest `job.json` |
| `GET /events?after=SEQ&limit=N&repo=R` | token | events in arrival order |

Tokens are per machine (`token add|list|remove`); only their hash is stored. It serves plain
HTTP: bind it to 127.0.0.1 or put TLS in front before exposing it.

The event format is defined by software-factory (DESIGN.md · Events); see
[ADR 0001](docs/adr/0001-events-are-owned-by-the-factory.md).

## Develop

`factory/checks.sh` is the single check: ruff, mypy `--strict`, unittest and a wheel build.
