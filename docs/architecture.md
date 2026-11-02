# Architecture

```text
src/factory_office/
  store.py    SQLite: schema, validation of schema-1 events, idempotent ingest, projection, tokens
  server.py   ThreadingHTTPServer: /health, POST /events, GET /state, GET /events
  cli.py      serve, token, state, tail
  web/
    index.html  the page shell (no inline script or style: CSP 'self')
    model.js    pure functions over /state and /stream data: zones, who is working, counts, SSE parsing
    client.js   HTTP only: token, GET /state, the /stream loop with reconnects, GET /events
    office.js   Canvas renderer and panels; reads the office only through model.js
```

Allowed imports: `cli → server → store`, `cli → store`. `store` imports only the standard library.
In the browser: `office.js → client.js, model.js`; `model.js` imports nothing. Replacing the
Canvas renderer (Phaser + Tiled) means replacing `office.js` only.

## Where a job sits

`model.placeFor(job)` maps the stage, and the claim from its latest `job.json`, to a zone and to
"someone is working". Tickets: intake → reception, needs-info → waiting, build → workshop,
gate → QA, review → review, merging → elevator, ready → outbox, needs-human → human, done →
archive, rejected → bin. Specs: building → listed in the room header, final-review → review (or
QA while its final gate runs), final-build → workshop.

## Data

| Table | Holds | Written by |
| --- | --- | --- |
| `events` | every event once (`id` unique), with `seq` in arrival order and the raw JSON | ingest |
| `jobs` | per `repo` + `job_id`: latest stage, `ts`, machine and last known `job.json` | ingest (projection) |
| `repos` | per `repo` + `machine`: last time seen | ingest (projection) |
| `tokens` | sha256 of each token, its name and role (`emit` or `view`) | `token add` |

Projection rule: an event updates its job only if its `ts` is not older than the stored one
(ties go to the last received). An event without a snapshot moves the stage and keeps the
previous snapshot. One invalid event rejects the whole batch, so a 2xx means everything is stored.

## Live updates

`GET /stream` polls the `events` table once a second per open page and sends each new event
together with its job's projected state, so the page never re-reads `/state` except to recover
from a disconnect (it resumes from the last `seq` it saw).

## Next

- Phaser + Tiled renderer with the user's own tilesets, replacing `office.js`.
