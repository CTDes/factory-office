# Architecture

```text
src/factory_office/
  store.py    SQLite: schema, validation of schema-1 events, idempotent ingest, projection, tokens
  server.py   ThreadingHTTPServer: /health, POST /events, GET /state, GET /events
  cli.py      serve, token, state, tail
```

Allowed imports: `cli → server → store`, `cli → store`. `store` imports only the standard library.

## Data

| Table | Holds | Written by |
| --- | --- | --- |
| `events` | every event once (`id` unique), with `seq` in arrival order and the raw JSON | ingest |
| `jobs` | per `repo` + `job_id`: latest stage, `ts`, machine and last known `job.json` | ingest (projection) |
| `repos` | per `repo` + `machine`: last time seen | ingest (projection) |
| `tokens` | sha256 of each machine's token | `token add` |

Projection rule: an event updates its job only if its `ts` is not older than the stored one
(ties go to the last received). An event without a snapshot moves the stage and keeps the
previous snapshot. One invalid event rejects the whole batch, so a 2xx means everything is stored.

## Next

- The web office: `GET /` serving the pixel-art page, fed by `/state` and a stream of events.
  Rendering stays separate from the data client so Canvas can later be replaced by Phaser + Tiled.
