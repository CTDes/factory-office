"""factory-office: serve the collector, manage machine tokens, and read the office from a shell."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sqlite3
import sys
import time
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from factory_office import server, store

DB_ENV = "FACTORY_OFFICE_DB"
FINISHED = ("done", "rejected")
STAGE_ORDER = (
    "intake",
    "needs-info",
    "build",
    "gate",
    "review",
    "merging",
    "ready",
    "needs-human",
    "building",
    "final-gate",
    "final-review",
    "final-build",
)


def default_db() -> Path:
    env = os.environ.get(DB_ENV, "").strip()
    if env:
        return Path(env).expanduser()
    base = Path(os.environ.get("XDG_DATA_HOME", "~/.local/share")).expanduser()
    return base / "factory-office" / "office.db"


# ---------------------------------------------------------------- formatting


def local_time(ts: str) -> str:
    try:
        return dt.datetime.fromtimestamp(store.parse_ts(ts)).strftime("%m-%d %H:%M:%S")
    except ValueError:
        return ts


def format_event(e: dict[str, Any]) -> str:
    return (
        f"{local_time(e['ts'])}  {e['repo']:<28}  {e['job_id'][:36]:<36}  "
        f"{e['from']} → {e['to']:<12}  {e['reason']}"
    )


def _rank(stage: str) -> int:
    return STAGE_ORDER.index(stage) if stage in STAGE_ORDER else len(STAGE_ORDER)


def format_state(snapshot: dict[str, Any], show_all: bool = False) -> str:
    lines: list[str] = []
    by_repo: dict[str, list[dict[str, Any]]] = {}
    for job in snapshot["jobs"]:
        by_repo.setdefault(job["repo"], []).append(job)
    seen: dict[str, list[str]] = {}
    for r in snapshot["repos"]:
        seen.setdefault(r["repo"], []).append(f"{r['machine']} · {local_time(r['last_seen'])}")
    for repo in sorted(set(by_repo) | set(seen)):
        jobs = by_repo.get(repo, [])
        counts = Counter(j["stage"] for j in jobs)
        live = [j for j in jobs if show_all or j["stage"] not in FINISHED]
        finished = ", ".join(f"{counts[s]} {s}" for s in FINISHED if counts[s])
        lines.append(f"{repo}  ({'; '.join(seen.get(repo, []))})")
        lines.append(f"  {len(live)} active" + (f" · {finished}" if finished else ""))
        for j in sorted(live, key=lambda j: (_rank(j["stage"]), j["job_id"])):
            snap = j.get("job") or {}
            extra = []
            if snap.get("round"):
                extra.append(f"round {snap['round']}")
            if snap.get("risk"):
                extra.append(str(snap["risk"]))
            if snap.get("pr"):
                extra.append(f"PR #{snap['pr']}")
            title = snap.get("title") or ""
            detail = " · ".join(extra)
            lines.append(f"  {j['stage']:<12} {j['job_id'][:40]:<40} {detail:<24} {title}".rstrip())
        lines.append("")
    return "\n".join(lines).rstrip() or "no events yet"


# ---------------------------------------------------------------- commands


def _with_db(db: Path, fn: Callable[[sqlite3.Connection], int]) -> int:
    conn = store.connect(db)
    try:
        return fn(conn)
    finally:
        conn.close()


def cmd_serve(args: argparse.Namespace) -> int:
    srv = server.OfficeServer((args.host, args.port), args.db, quiet=not args.verbose)
    host, port = srv.server_address[:2]
    print(f"factory-office: office at http://{host!s}:{port}/ · db {args.db}", flush=True)
    print("factory-office: show the office token with: factory-office token", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


def cmd_token(args: argparse.Namespace) -> int:
    def run(conn: sqlite3.Connection) -> int:
        if args.rotate:
            print(store.rotate_token(conn))
            print(
                "Rotated. Every linked repository must link again: factory-job office link <token>",
                file=sys.stderr,
            )
            return 0
        print(store.office_token(conn))
        return 0

    return _with_db(args.db, run)


def cmd_state(args: argparse.Namespace) -> int:
    return _with_db(args.db, lambda conn: _print(format_state(store.state(conn), args.all)))


def _print(text: str) -> int:
    print(text)
    return 0


def cmd_tail(args: argparse.Namespace) -> int:
    def run(conn: sqlite3.Connection) -> int:
        last = 0
        for e in store.last_events(conn, args.lines, args.repo):
            print(format_event(e))
            last = e["seq"]
        if not args.follow:
            return 0
        if last == 0:
            row = conn.execute("SELECT COALESCE(MAX(seq), 0) FROM events").fetchone()
            last = int(row[0])
        try:
            while True:
                for e in store.events_after(conn, last, 500, args.repo):
                    print(format_event(e), flush=True)
                    last = e["seq"]
                time.sleep(args.interval)
        except KeyboardInterrupt:
            return 0

    return _with_db(args.db, run)


# ---------------------------------------------------------------- entry point


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="factory-office", description="Collector and office view for software-factory events"
    )
    p.add_argument(
        "--db", type=Path, default=None, help=f"SQLite file (default: ${DB_ENV} or ~/.local/share)"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run the collector")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--verbose", action="store_true", help="log every request")
    s.set_defaults(fn=cmd_serve)

    t = sub.add_parser("token", help="print the office token (factories link with it)")
    t.add_argument("--rotate", action="store_true", help="replace it; every repo links again")
    t.set_defaults(fn=cmd_token)

    st = sub.add_parser("state", help="latest state of every repo and job")
    st.add_argument("--all", action="store_true", help="include done and rejected jobs")
    st.set_defaults(fn=cmd_state)

    tl = sub.add_parser("tail", help="recent events, like events.log for every repo")
    tl.add_argument("-n", "--lines", type=int, default=20)
    tl.add_argument("-f", "--follow", action="store_true")
    tl.add_argument("--repo")
    tl.add_argument("--interval", type=float, default=1.0, help=argparse.SUPPRESS)
    tl.set_defaults(fn=cmd_tail)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.db is None:
        args.db = default_db()
    result: int = args.fn(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
