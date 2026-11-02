# factory-office

Collector and (soon) office view for software-factory events. Standard library only.

## Setup and validation

- Python 3.10+. No runtime dependencies; dev tools in `requirements-dev.txt`.
- `factory/checks.sh` is the single source of truth: `ruff check`, `ruff format --check`,
  `mypy --strict`, `unittest` over `tests/`, wheel build. It creates `.venv/` on first run.
- One test: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_store -k ingest`.
- Format before committing: `.venv/bin/python -m ruff format .`.

## Conventions

- Layers in `docs/architecture.md`: `store` knows SQLite, `server` knows HTTP, `cli` knows the
  shell. `store` imports neither of the others.
- The event format belongs to software-factory (`plugin/DESIGN.md · Events` there). Never change
  what an event means here; accept unknown fields, reject unknown `schema` values.
- The database is a projection. Anything in it must be rebuildable from the repositories with
  `factory-job events backfill`.
- Tests use `unittest`, one `TestCase` per public function or route, named `test_<behaviour>`.
  `tests/fixtures/events_v1.jsonl` holds real events built by the factory's own emitter; regenerate
  it, never hand-edit it, when the factory's format changes.
- Web: no inline scripts or styles (the page has CSP `'self'`); build DOM with `office.js`'s `h()`
  helper, never `innerHTML`. Office logic belongs in `web/model.js`, tested in `tests/js/`; the
  renderer only draws.
- Architecture decisions: `docs/adr/`.
