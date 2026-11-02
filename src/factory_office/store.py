"""SQLite store: every event (append-only) and, per job, the latest known state.

The repositories stay the source of truth (their job.json files). This database is a projection
that can be deleted and rebuilt with ``factory-job events backfill`` in each repository.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import secrets
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EVENT_SCHEMA = 1

_DDL = """
CREATE TABLE IF NOT EXISTS events (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    id          TEXT    NOT NULL UNIQUE,
    repo        TEXT    NOT NULL,
    machine     TEXT    NOT NULL,
    sender      TEXT    NOT NULL,
    job_id      TEXT    NOT NULL,
    ts          TEXT    NOT NULL,
    ts_epoch    REAL    NOT NULL,
    from_stage  TEXT    NOT NULL,
    to_stage    TEXT    NOT NULL,
    reason      TEXT    NOT NULL,
    received_at TEXT    NOT NULL,
    raw         TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS events_by_job ON events (repo, job_id, ts_epoch);

CREATE TABLE IF NOT EXISTS jobs (
    repo      TEXT    NOT NULL,
    job_id    TEXT    NOT NULL,
    kind      TEXT,
    issue     INTEGER,
    spec      TEXT,
    stage     TEXT    NOT NULL,
    ts        TEXT    NOT NULL,
    ts_epoch  REAL    NOT NULL,
    machine   TEXT    NOT NULL,
    snapshot  TEXT,
    PRIMARY KEY (repo, job_id)
);

CREATE TABLE IF NOT EXISTS repos (
    repo      TEXT NOT NULL,
    machine   TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    last_seen_epoch REAL NOT NULL,
    PRIMARY KEY (repo, machine)
);

CREATE TABLE IF NOT EXISTS tokens (
    hash       TEXT PRIMARY KEY,
    machine    TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
"""

_LIMITS = {"id": 64, "repo": 200, "machine": 200, "job_id": 200, "from": 64, "to": 64}
MAX_REASON = 4000
MAX_SNAPSHOT_BYTES = 64 * 1024


class InvalidEvent(ValueError):
    """An event that does not follow schema 1. ``index`` is its position in the batch."""

    def __init__(self, message: str, index: int | None = None) -> None:
        super().__init__(message)
        self.index = index


@dataclass(frozen=True)
class Event:
    id: str
    repo: str
    machine: str
    job_id: str
    kind: str | None
    issue: int | None
    spec: str | None
    ts: str
    ts_epoch: float
    frm: str
    to: str
    reason: str
    job: dict[str, Any] | None
    raw: str


@dataclass(frozen=True)
class IngestResult:
    accepted: int
    duplicates: int


# ---------------------------------------------------------------- connection


def connect(path: Path | str) -> sqlite3.Connection:
    """Open (and create if needed) the database. One connection per thread."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(_DDL)
    return conn


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def parse_ts(value: str) -> float:
    """Epoch seconds of an ISO 8601 timestamp with offset ('Z' accepted, naive refused)."""
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("timestamp without offset")
    return parsed.timestamp()


# ---------------------------------------------------------------- validation


def _text(event: dict[str, Any], key: str, limit: int) -> str:
    value = event.get(key)
    if not isinstance(value, str) or not value or len(value) > limit:
        raise InvalidEvent(f"'{key}' must be a non-empty string of at most {limit} characters")
    return value


def validate(event: Any) -> Event:
    """Check one event against schema 1 (software-factory DESIGN.md · Events)."""
    if not isinstance(event, dict):
        raise InvalidEvent("an event must be a JSON object")
    if event.get("schema") != EVENT_SCHEMA:
        raise InvalidEvent(f"unsupported schema {event.get('schema')!r}; this collector reads 1")
    fields = {key: _text(event, key, limit) for key, limit in _LIMITS.items()}
    ts = event.get("ts")
    if not isinstance(ts, str):
        raise InvalidEvent("'ts' must be an ISO 8601 string")
    try:
        ts_epoch = parse_ts(ts)
    except ValueError as exc:
        raise InvalidEvent(f"'ts' is not an ISO 8601 timestamp with offset: {ts!r}") from exc
    reason = event.get("reason")
    if not isinstance(reason, str) or len(reason) > MAX_REASON:
        raise InvalidEvent(f"'reason' must be a string of at most {MAX_REASON} characters")
    issue = event.get("issue")
    if issue is not None and (not isinstance(issue, int) or isinstance(issue, bool)):
        raise InvalidEvent("'issue' must be an integer or null")
    kind, spec = event.get("kind"), event.get("spec")
    for key, value in (("kind", kind), ("spec", spec)):
        if value is not None and not isinstance(value, str):
            raise InvalidEvent(f"'{key}' must be a string or null")
    job = event.get("job")
    if job is not None:
        if not isinstance(job, dict):
            raise InvalidEvent("'job' must be an object or null")
        if len(json.dumps(job, ensure_ascii=False).encode("utf-8")) > MAX_SNAPSHOT_BYTES:
            raise InvalidEvent(f"'job' snapshot is larger than {MAX_SNAPSHOT_BYTES} bytes")
    return Event(
        id=fields["id"],
        repo=fields["repo"],
        machine=fields["machine"],
        job_id=fields["job_id"],
        kind=kind,
        issue=issue,
        spec=spec,
        ts=ts,
        ts_epoch=ts_epoch,
        frm=fields["from"],
        to=fields["to"],
        reason=reason,
        job=job,
        raw=json.dumps(event, ensure_ascii=False, sort_keys=True),
    )


# ---------------------------------------------------------------- ingest


def ingest(conn: sqlite3.Connection, batch: Sequence[Any], sender: str) -> IngestResult:
    """Store a batch atomically. Duplicate ids are skipped; one invalid event rejects all."""
    parsed: list[Event] = []
    for i, raw in enumerate(batch):
        try:
            parsed.append(validate(raw))
        except InvalidEvent as exc:
            raise InvalidEvent(f"event {i}: {exc}", index=i) from exc
    accepted = 0
    received = _now()
    conn.execute("BEGIN IMMEDIATE")
    try:
        for ev in parsed:
            cur = conn.execute(
                "INSERT OR IGNORE INTO events (id, repo, machine, sender, job_id, ts, ts_epoch,"
                " from_stage, to_stage, reason, received_at, raw)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ev.id,
                    ev.repo,
                    ev.machine,
                    sender,
                    ev.job_id,
                    ev.ts,
                    ev.ts_epoch,
                    ev.frm,
                    ev.to,
                    ev.reason,
                    received,
                    ev.raw,
                ),
            )
            if cur.rowcount == 0:
                continue
            accepted += 1
            _project(conn, ev)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return IngestResult(accepted=accepted, duplicates=len(parsed) - accepted)


def _project(conn: sqlite3.Connection, ev: Event) -> None:
    """Fold one new event into ``jobs`` and ``repos``. Newest ``ts`` wins; ties go to the last."""
    row = conn.execute(
        "SELECT ts_epoch, snapshot FROM jobs WHERE repo = ? AND job_id = ?", (ev.repo, ev.job_id)
    ).fetchone()
    if row is None or ev.ts_epoch >= row["ts_epoch"]:
        snapshot = (
            json.dumps(ev.job, ensure_ascii=False) if ev.job is not None else _keep(row, "snapshot")
        )
        conn.execute(
            "INSERT INTO jobs (repo, job_id, kind, issue, spec, stage, ts, ts_epoch, machine,"
            " snapshot) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (repo, job_id) DO UPDATE SET"
            " kind = COALESCE(excluded.kind, kind), issue = COALESCE(excluded.issue, issue),"
            " spec = COALESCE(excluded.spec, spec), stage = excluded.stage, ts = excluded.ts,"
            " ts_epoch = excluded.ts_epoch, machine = excluded.machine,"
            " snapshot = excluded.snapshot",
            (
                ev.repo,
                ev.job_id,
                ev.kind,
                ev.issue,
                ev.spec,
                ev.to,
                ev.ts,
                ev.ts_epoch,
                ev.machine,
                snapshot,
            ),
        )
    conn.execute(
        "INSERT INTO repos (repo, machine, last_seen, last_seen_epoch) VALUES (?, ?, ?, ?)"
        " ON CONFLICT (repo, machine) DO UPDATE SET"
        " last_seen = CASE WHEN excluded.last_seen_epoch > last_seen_epoch"
        "   THEN excluded.last_seen ELSE last_seen END,"
        " last_seen_epoch = MAX(last_seen_epoch, excluded.last_seen_epoch)",
        (ev.repo, ev.machine, ev.ts, ev.ts_epoch),
    )


def _keep(row: sqlite3.Row | None, key: str) -> Any:
    return row[key] if row is not None else None


# ---------------------------------------------------------------- queries


def state(conn: sqlite3.Connection) -> dict[str, Any]:
    """Every repo and the latest state of every job, with its job.json snapshot if known."""
    repos = [
        {"repo": r["repo"], "machine": r["machine"], "last_seen": r["last_seen"]}
        for r in conn.execute("SELECT * FROM repos ORDER BY repo, machine")
    ]
    jobs = [
        {
            "repo": r["repo"],
            "job_id": r["job_id"],
            "kind": r["kind"],
            "issue": r["issue"],
            "spec": r["spec"],
            "stage": r["stage"],
            "ts": r["ts"],
            "machine": r["machine"],
            "job": json.loads(r["snapshot"]) if r["snapshot"] else None,
        }
        for r in conn.execute("SELECT * FROM jobs ORDER BY repo, job_id")
    ]
    return {"repos": repos, "jobs": jobs}


def events_after(
    conn: sqlite3.Connection, after: int = 0, limit: int = 500, repo: str | None = None
) -> list[dict[str, Any]]:
    """Events in arrival order with ``seq`` greater than ``after``."""
    sql = "SELECT * FROM events WHERE seq > ?"
    args: list[Any] = [after]
    if repo:
        sql += " AND repo = ?"
        args.append(repo)
    sql += " ORDER BY seq LIMIT ?"
    args.append(max(1, min(limit, 5000)))
    return [_event_row(r) for r in conn.execute(sql, args)]


def last_events(
    conn: sqlite3.Connection, count: int, repo: str | None = None
) -> list[dict[str, Any]]:
    """The ``count`` most recent events by arrival, oldest first."""
    sql = "SELECT * FROM events"
    args: list[Any] = []
    if repo:
        sql += " WHERE repo = ?"
        args.append(repo)
    sql += " ORDER BY seq DESC LIMIT ?"
    args.append(max(0, count))
    return [_event_row(r) for r in reversed(conn.execute(sql, args).fetchall())]


def _event_row(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "seq": r["seq"],
        "id": r["id"],
        "repo": r["repo"],
        "machine": r["machine"],
        "sender": r["sender"],
        "job_id": r["job_id"],
        "ts": r["ts"],
        "from": r["from_stage"],
        "to": r["to_stage"],
        "reason": r["reason"],
    }


# ---------------------------------------------------------------- tokens


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def add_token(conn: sqlite3.Connection, machine: str) -> str:
    """Create (or rotate) the token of a machine. Only its hash is stored."""
    if not machine.strip():
        raise ValueError("machine name must not be empty")
    token = secrets.token_urlsafe(32)
    conn.execute("DELETE FROM tokens WHERE machine = ?", (machine,))
    conn.execute(
        "INSERT INTO tokens (hash, machine, created_at) VALUES (?, ?, ?)",
        (_hash(token), machine, _now()),
    )
    return token


def check_token(conn: sqlite3.Connection, token: str) -> str | None:
    """The machine a token belongs to, or None."""
    if not token:
        return None
    row = conn.execute("SELECT machine FROM tokens WHERE hash = ?", (_hash(token),)).fetchone()
    return str(row["machine"]) if row else None


def list_tokens(conn: sqlite3.Connection) -> list[dict[str, str]]:
    return [
        {"machine": r["machine"], "created_at": r["created_at"]}
        for r in conn.execute("SELECT machine, created_at FROM tokens ORDER BY machine")
    ]


def remove_token(conn: sqlite3.Connection, machine: str) -> bool:
    return conn.execute("DELETE FROM tokens WHERE machine = ?", (machine,)).rowcount > 0


def has_tokens(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM tokens LIMIT 1").fetchone() is not None
