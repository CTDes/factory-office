"""Shared test data: events of schema 1 like the ones software-factory 0.3.0 emits."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURE = Path(__file__).parent / "fixtures" / "events_v1.jsonl"


def fixture_events() -> list[dict[str, Any]]:
    """Real events: factory-sandbox's jobs, built with software-factory's own make_event."""
    return [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]


def event(
    n: int = 1,
    *,
    repo: str = "CTDes/textkit",
    job_id: str = "012-reading-time",
    ts: str = "2026-11-02T10:00:00+01:00",
    frm: str = "intake",
    to: str = "build",
    reason: str = "ACCEPT",
    job: dict[str, Any] | bool | None = True,
    **extra: Any,
) -> dict[str, Any]:
    snapshot: dict[str, Any] | None
    if job is True:
        snapshot = {"id": job_id, "stage": to, "round": 1, "title": "Reading time", "risk": "low"}
    elif job is False:
        snapshot = None
    else:
        snapshot = job
    data: dict[str, Any] = {
        "schema": 1,
        "id": f"ev{n:04d}-{job_id}",
        "repo": repo,
        "machine": "mac-1",
        "job_id": job_id,
        "kind": "ticket",
        "issue": 12,
        "spec": None,
        "ts": ts,
        "from": frm,
        "to": to,
        "reason": reason,
        "job": snapshot,
    }
    data.update(extra)
    return data
