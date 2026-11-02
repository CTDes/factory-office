"""The SQLite store: validation, idempotent ingest, the per-job projection, queries, tokens."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from factory_office import store
from helpers import event, fixture_events


def memory() -> sqlite3.Connection:
    return store.connect(":memory:")


class ValidateTest(unittest.TestCase):
    def test_accepts_a_schema_1_event(self) -> None:
        ev = store.validate(event())
        self.assertEqual(
            (ev.repo, ev.job_id, ev.frm, ev.to),
            ("CTDes/textkit", "012-reading-time", "intake", "build"),
        )

    def test_accepts_every_real_fixture_event(self) -> None:
        for raw in fixture_events():
            store.validate(raw)

    def test_rejects_other_schemas_and_missing_fields(self) -> None:
        cases = {
            "schema": event(schema=2),
            "'repo'": event(repo=""),
            "'ts'": event(ts="yesterday"),
            "offset": event(ts="2026-11-02T10:00:00"),
            "'issue'": event(issue="12"),
            "'job'": {**event(), "job": ["x"]},
            "object": "not an event",
        }
        for message, raw in cases.items():
            with self.assertRaisesRegex(store.InvalidEvent, message):
                store.validate(raw)

    def test_rejects_huge_snapshots(self) -> None:
        with self.assertRaisesRegex(store.InvalidEvent, "larger than"):
            store.validate(event(job={"blob": "x" * (store.MAX_SNAPSHOT_BYTES + 1)}))

    def test_accepts_z_timestamps(self) -> None:
        self.assertEqual(
            store.validate(event(ts="2026-11-02T09:00:00Z")).ts_epoch,
            store.parse_ts("2026-11-02T10:00:00+01:00"),
        )


class IngestTest(unittest.TestCase):
    def test_duplicates_are_skipped(self) -> None:
        conn = memory()
        self.assertEqual(
            store.ingest(conn, [event(1), event(2, to="gate")], "mac-1"), store.IngestResult(2, 0)
        )
        self.assertEqual(
            store.ingest(conn, [event(1), event(3, to="review")], "mac-1"), store.IngestResult(1, 1)
        )
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0], 3)

    def test_one_invalid_event_rejects_the_whole_batch(self) -> None:
        conn = memory()
        with self.assertRaises(store.InvalidEvent) as caught:
            store.ingest(conn, [event(1), event(2, ts="bad")], "mac-1")
        self.assertEqual(caught.exception.index, 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0], 0)

    def test_newest_event_sets_the_job_state(self) -> None:
        conn = memory()
        store.ingest(
            conn,
            [
                event(2, ts="2026-11-02T10:05:00+01:00", frm="build", to="gate", reason="READY"),
                event(1, ts="2026-11-02T10:00:00+01:00", frm="intake", to="build"),
            ],
            "mac-1",
        )
        (job,) = store.state(conn)["jobs"]
        self.assertEqual(job["stage"], "gate")
        self.assertEqual(job["job"]["stage"], "gate")

    def test_event_without_snapshot_moves_stage_and_keeps_last_snapshot(self) -> None:
        conn = memory()
        store.ingest(conn, [event(1, to="build")], "mac-1")
        store.ingest(
            conn,
            [event(2, ts="2026-11-02T10:01:00+01:00", frm="build", to="gate", job=False)],
            "mac-1",
        )
        (job,) = store.state(conn)["jobs"]
        self.assertEqual(job["stage"], "gate")
        self.assertEqual(job["job"]["title"], "Reading time")

    def test_real_backfill_projects_to_current_job_json(self) -> None:
        conn = memory()
        evs = fixture_events()
        result = store.ingest(conn, evs, "fixture")
        self.assertEqual(result.accepted, len(evs))
        jobs = {j["job_id"]: j for j in store.state(conn)["jobs"]}
        for raw in evs:
            if raw["job"] is not None:
                self.assertEqual(jobs[raw["job_id"]]["stage"], raw["job"]["stage"])
        self.assertEqual(store.ingest(conn, evs, "fixture"), store.IngestResult(0, len(evs)))

    def test_sender_is_recorded_apart_from_machine(self) -> None:
        conn = memory()
        store.ingest(conn, [event(1)], "token-name")
        (row,) = store.events_after(conn)
        self.assertEqual((row["machine"], row["sender"]), ("mac-1", "token-name"))


class StateTest(unittest.TestCase):
    def test_lists_repos_per_machine_with_latest_time(self) -> None:
        conn = memory()
        store.ingest(
            conn,
            [
                event(1, ts="2026-11-02T10:00:00+01:00"),
                event(2, ts="2026-11-02T09:00:00+01:00", job_id="013-x"),
                event(3, repo="CTDes/factory-sandbox", machine="mac-2"),
            ],
            "s",
        )
        repos = store.state(conn)["repos"]
        self.assertEqual(
            [(r["repo"], r["machine"], r["last_seen"]) for r in repos],
            [
                ("CTDes/factory-sandbox", "mac-2", "2026-11-02T10:00:00+01:00"),
                ("CTDes/textkit", "mac-1", "2026-11-02T10:00:00+01:00"),
            ],
        )

    def test_empty_database(self) -> None:
        self.assertEqual(store.state(memory()), {"repos": [], "jobs": []})


class EventsAfterTest(unittest.TestCase):
    def test_pages_in_arrival_order_and_filters_by_repo(self) -> None:
        conn = memory()
        store.ingest(conn, [event(i, repo="a/x" if i % 2 else "b/y") for i in range(1, 7)], "s")
        first = store.events_after(conn, 0, 2)
        self.assertEqual([e["seq"] for e in first], [1, 2])
        rest = store.events_after(conn, first[-1]["seq"])
        self.assertEqual([e["seq"] for e in rest], [3, 4, 5, 6])
        self.assertEqual({e["repo"] for e in store.events_after(conn, 0, repo="b/y")}, {"b/y"})


class LastEventsTest(unittest.TestCase):
    def test_returns_most_recent_oldest_first(self) -> None:
        conn = memory()
        store.ingest(conn, [event(i) for i in range(1, 6)], "s")
        self.assertEqual([e["seq"] for e in store.last_events(conn, 2)], [4, 5])


class TokensTest(unittest.TestCase):
    def test_add_check_rotate_remove(self) -> None:
        conn = memory()
        first = store.add_token(conn, "mac-1")
        self.assertEqual(store.check_token(conn, first), "mac-1")
        second = store.add_token(conn, "mac-1")
        self.assertIsNone(store.check_token(conn, first))
        self.assertEqual(store.check_token(conn, second), "mac-1")
        self.assertEqual([t["machine"] for t in store.list_tokens(conn)], ["mac-1"])
        self.assertTrue(store.remove_token(conn, "mac-1"))
        self.assertFalse(store.has_tokens(conn))
        self.assertIsNone(store.check_token(conn, ""))

    def test_only_the_hash_is_stored(self) -> None:
        conn = memory()
        token = store.add_token(conn, "mac-1")
        dump = "\n".join(conn.iterdump())
        self.assertNotIn(token, dump)


class ConnectTest(unittest.TestCase):
    def test_creates_parent_folders_and_survives_reopen(self) -> None:
        path = Path(tempfile.mkdtemp()) / "deep" / "office.db"
        conn = store.connect(path)
        store.ingest(conn, [event(1)], "s")
        conn.close()
        self.assertEqual(len(store.events_after(store.connect(path))), 1)


if __name__ == "__main__":
    unittest.main()
