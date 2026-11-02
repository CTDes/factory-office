"""The HTTP collector, on 127.0.0.1 with a temporary database."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from factory_office import server, store
from helpers import event, fixture_events


class ServerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.db = Path(tempfile.mkdtemp()) / "office.db"
        self.srv = server.make_server(self.db, port=0)
        port = self.srv.server_address[1]
        self.base = f"http://127.0.0.1:{port}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        conn = store.connect(self.db)
        self.token = store.add_token(conn, "mac-1")
        conn.close()

    def call(
        self,
        method: str,
        path: str,
        body: Any = None,
        token: str | None = "default",
        raw: bytes | None = None,
    ) -> tuple[int, Any]:
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if token is not None:
            req.add_header("Authorization", f"Bearer {self.token if token == 'default' else token}")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as err:
            with err:
                return err.code, json.loads(err.read())


class HealthTest(ServerTestCase):
    def test_health_needs_no_token(self) -> None:
        self.assertEqual(self.call("GET", "/health", token=None), (200, {"ok": True}))

    def test_unknown_route_is_404(self) -> None:
        self.assertEqual(self.call("GET", "/nope")[0], 404)
        self.assertEqual(self.call("POST", "/nope", {"events": []})[0], 404)


class PostEventsTest(ServerTestCase):
    def test_requires_a_known_token(self) -> None:
        self.assertEqual(self.call("POST", "/events", {"events": [event()]}, token=None)[0], 401)
        self.assertEqual(self.call("POST", "/events", {"events": [event()]}, token="wrong")[0], 401)

    def test_accepts_real_events_and_counts_duplicates(self) -> None:
        evs = fixture_events()
        self.assertEqual(
            self.call("POST", "/events", {"events": evs}),
            (200, {"accepted": len(evs), "duplicates": 0}),
        )
        self.assertEqual(
            self.call("POST", "/events", {"events": evs}),
            (200, {"accepted": 0, "duplicates": len(evs)}),
        )

    def test_bad_bodies_are_400_and_store_nothing(self) -> None:
        self.assertEqual(self.call("POST", "/events", raw=b"{nope")[0], 400)
        self.assertEqual(self.call("POST", "/events", {"evts": []})[0], 400)
        status, body = self.call("POST", "/events", {"events": [event(1), event(2, schema=9)]})
        self.assertEqual((status, body["index"]), (400, 1))
        self.assertIn("schema", body["error"])
        self.assertEqual(self.call("GET", "/events")[1], {"events": []})

    def test_too_many_events_is_413(self) -> None:
        original = server.MAX_BATCH
        server.MAX_BATCH = 2
        self.addCleanup(setattr, server, "MAX_BATCH", original)
        self.assertEqual(
            self.call("POST", "/events", {"events": [event(i) for i in range(3)]})[0], 413
        )

    def test_works_with_the_factory_emitter_payload(self) -> None:
        # software-factory posts exactly {"events": [...]} with a bearer token
        status, body = self.call("POST", "/events", {"events": [event(1)]})
        self.assertEqual((status, body["accepted"]), (200, 1))


class GetStateTest(ServerTestCase):
    def test_state_shows_latest_stage(self) -> None:
        self.call(
            "POST",
            "/events",
            {
                "events": [
                    event(1),
                    event(2, ts="2026-11-02T10:09:00+01:00", frm="build", to="gate"),
                ]
            },
        )
        status, body = self.call("GET", "/state")
        self.assertEqual(status, 200)
        self.assertEqual(
            [(j["job_id"], j["stage"]) for j in body["jobs"]], [("012-reading-time", "gate")]
        )
        self.assertEqual(self.call("GET", "/state", token=None)[0], 401)


class GetEventsTest(ServerTestCase):
    def test_pages_with_after(self) -> None:
        self.call("POST", "/events", {"events": [event(i) for i in range(1, 4)]})
        first = self.call("GET", "/events?limit=2")[1]["events"]
        self.assertEqual([e["seq"] for e in first], [1, 2])
        rest = self.call("GET", f"/events?after={first[-1]['seq']}")[1]["events"]
        self.assertEqual([e["seq"] for e in rest], [3])
        self.assertEqual(self.call("GET", "/events?after=x")[0], 400)


if __name__ == "__main__":
    unittest.main()
