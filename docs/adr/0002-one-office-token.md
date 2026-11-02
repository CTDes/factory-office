# 0002 · One office token; repositories opt in with `office link`

Date: 2026-11-02 · Status: accepted · Supersedes the per-machine tokens of 0.1.0–0.2.0

## Context

0.1.0 and 0.2.0 had a token per machine (send) or viewer (read), and each machine configured
`FACTORY_EVENTS_URL` and `FACTORY_EVENTS_TOKEN` for all its repositories at once. The owner wants
the office isolated in Docker and to choose repository by repository what it shows, with one
command and one secret.

## Decision

- The office has a single token, created on first start and stored in its database. It sends
  events and opens the page. `factory-office token` shows it; `--rotate` replaces it.
- A repository opts in with `factory-job office link <token> [--url URL]` (software-factory
  0.4.0), which checks the token with an empty `POST /events`, saves the link in the gitignored
  `factory/jobs/_events/link.json` and sends the history. The environment variables remain for CI.
- The office runs in Docker: non-root, read-only filesystem, database in a volume, port on
  127.0.0.1 unless the owner publishes it behind TLS.

## Consequences

- Simpler to run: one secret, one command per repository.
- No per-machine revocation: losing a machine means rotating the token and linking every
  repository again.
- The `machine` in an event is what the sender says; the office cannot verify it.
- Whoever opens the page holds a token that can also send events. Acceptable for a personal or
  small-team office; a read-only token can come back later without changing `office link`.
