# 0001 · Events are owned by the factory; the office only reads them

Date: 2026-11-02 · Status: accepted

## Context

We want to see every repository that runs the software factory, including repositories on other
machines, in one place. Options were: a second Claude Code plugin in every repository, reading
GitHub labels, or the factory pushing its own transitions to a collector.

## Decision

- software-factory 0.3.0 emits every transition (`Job.log_event`) to `FACTORY_EVENTS_URL`
  through a local outbox. The format, schema 1, is defined in its `plugin/DESIGN.md · Events`.
- factory-office is a separate service with its own SQLite database. It never writes to the
  repositories and never changes the format.
- The repositories stay the source of truth. The database is a projection that can be rebuilt
  with `factory-job events backfill`.

## Consequences

- No plugin per repository; one environment variable per machine.
- GitHub labels were not enough: they cannot tell build, gate and review apart.
- A collector that is down never stops a factory; events wait in the outbox.
- A breaking change in the event means `schema: 2`; this collector rejects schemas it does not know.
