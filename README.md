# factory-office

One place to see what the [software factory](https://github.com/CTDes/software-factory) is doing
in every repository, on every machine.

Each factory (software-factory 0.3.0 or later; 0.3.1 to see agents at work) pushes its job
transitions here. factory-office stores them in SQLite and shows them as a pixel-art office: one
room per repository, folders for jobs, agents at their desks while they work.

```text
machine A: factory-job ──POST /events──┐
machine B: factory-job ──POST /events──┼──> factory-office ──> SQLite ──> GET /state, /events, tail
CI runner: factory-job ──POST /events──┘                                └──> the office page (GET /, /stream)
```

## Run it

Python 3.10+, standard library only.

```sh
pip install -e .                       # or: PYTHONPATH=src python3 -m factory_office ...
factory-office token add my-laptop     # machine token: sends events; printed once
factory-office token add carlos --view # viewer token: only reads; for the office page
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

Open `http://127.0.0.1:8765/` and paste a viewer token, or open `http://127.0.0.1:8765/#token=<token>`
once: the page keeps the token in the browser and removes it from the address bar.

- **Rooms**: reception (planner), waiting chairs (`needs-info`), workshop (two builders, queue on
  the floor), QA conveyor with a traffic light that flashes on gate verdicts, review desk, elevator
  to the spec branch (`merging`), outbox (`ready`), the human's office with an alarm
  (`needs-human`), archive and bin for finished jobs.
- An agent sits at its desk while its job holds a claim (`job start` … next transition).
  Hat = model, folder tab = risk. Specs still building are listed under the room's header.
- Click a folder, a person or a job in the list for its details, last events and GitHub links.

From a shell:

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
| `GET /state` | any token | `{"repos": [...], "jobs": [...], "seq": n}`, each job with its latest `job.json` |
| `GET /events?after=&limit=&last=&repo=&job_id=` | any token | events in arrival order |
| `GET /stream?after=SEQ` | any token | Server-Sent Events: each new event with its job's and repo's new state |
| `GET /`, `GET /static/<file>` | none | the office page; it asks for a token |

`POST /events` needs a machine token (role `emit`); viewer tokens (`--view`) only read. Only token
hashes are stored. The page is served with a strict Content-Security-Policy (`'self'` only). It serves plain
HTTP: bind it to 127.0.0.1 or put TLS in front before exposing it.

The event format is defined by software-factory (DESIGN.md · Events); see
[ADR 0001](docs/adr/0001-events-are-owned-by-the-factory.md).

## Develop

`factory/checks.sh` is the single check: ruff, mypy `--strict`, unittest, the web model's
`node --test` (skipped without node) and a wheel build.
