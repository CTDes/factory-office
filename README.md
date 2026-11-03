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

With Docker (isolated: its own volume for the database, published on 127.0.0.1 only):

```sh
docker compose up -d                                   # http://127.0.0.1:8765/
docker compose exec office factory-office token        # the office token
```

The office has a single token, created on first start. Whoever knows it can link a repository
and open the page. `factory-office token --rotate` replaces it; linked repositories then get 401
and must link again.

In each repository you want to see (software-factory 0.4.0 or later):

```sh
factory-job office link <office-token>                         # office on this machine
factory-job office link <office-token> --url http://nas:8765   # office on another machine
```

That checks the office accepts the token, saves the link (gitignored), and sends the repository's
history. `factory-job office status` and `office unlink` do what they say.

Developing on this machine, `compose.dev.yaml` makes the container run the checkout's `src/`, so
a merged change needs a restart, not a rebuild:

```sh
echo COMPOSE_FILE=compose.yaml:compose.dev.yaml > .env     # once (.env is gitignored)
docker compose up -d
git pull && docker compose restart                        # after each merge
```

Only a change to `Dockerfile` or `pyproject.toml` needs `docker compose up -d --build`.

Without Docker: `pip install -e .` and `factory-office serve` (database in
`~/.local/share/factory-office/`, or `$FACTORY_OFFICE_DB`).

To reach it from other machines, publish the port beyond 127.0.0.1 only behind TLS or on a
network you trust: the token travels in a header.

## Look at it

Open `http://127.0.0.1:8765/` and paste the office token, or open
`http://127.0.0.1:8765/#token=<token>` once: the page keeps the token in the browser and removes
it from the address bar.

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
| `POST /events` | token | body `{"events": [...]}`; `{"accepted": n, "duplicates": m}`. An empty batch checks a link |
| `GET /state` | token | `{"repos": [...], "jobs": [...], "seq": n}`, each job with its latest `job.json` |
| `GET /events?after=&limit=&last=&repo=&job_id=` | token | events in arrival order |
| `GET /stream?after=SEQ` | token | Server-Sent Events: each new event with its job's and repo's new state |
| `GET /`, `GET /static/<file>` | none | the office page; it asks for the token |

The page is served with a strict Content-Security-Policy (`'self'` only).

The event format is defined by software-factory (DESIGN.md · Events); see
[ADR 0001](docs/adr/0001-events-are-owned-by-the-factory.md).

## Develop

`factory/checks.sh` is the single check: ruff, mypy `--strict`, unittest, the web model's
`node --test` (skipped without node) and a wheel build.
