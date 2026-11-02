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
        self.viewer = store.add_token(conn, "alice", "view")
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


class RolesTest(ServerTestCase):
    def test_view_token_reads_but_cannot_send(self) -> None:
        status, body = self.call("POST", "/events", {"events": [event()]}, token=self.viewer)
        self.assertEqual(status, 403)
        self.assertIn("emit", body["error"])
        self.assertEqual(self.call("GET", "/state", token=self.viewer)[0], 200)
        self.assertEqual(self.call("GET", "/events", token=self.viewer)[0], 200)


class GetEventsFiltersTest(ServerTestCase):
    def test_last_and_job_filter(self) -> None:
        evs = [event(i) for i in range(1, 4)] + [event(9, job_id="099-other")]
        self.call("POST", "/events", {"events": evs})
        last = self.call("GET", "/events?last=2")[1]["events"]
        self.assertEqual([e["seq"] for e in last], [3, 4])
        only = self.call("GET", "/events?job_id=099-other&repo=CTDes/textkit")[1]["events"]
        self.assertEqual([e["job_id"] for e in only], ["099-other"])


class StaticTest(ServerTestCase):
    def fetch(self, path: str) -> tuple[int, dict[str, str], bytes]:
        try:
            with urllib.request.urlopen(self.base + path, timeout=5) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as err:
            with err:
                return err.code, dict(err.headers), err.read()

    def test_page_needs_no_token_and_carries_a_strict_csp(self) -> None:
        status, headers, body = self.fetch("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
        self.assertIn(b"/static/office.js", body)

    def test_scripts_are_served_with_their_type(self) -> None:
        for name in ("model.js", "client.js", "office.js", "office.css"):
            status, _headers, body = self.fetch("/static/" + name)
            self.assertEqual(status, 200, name)
            self.assertTrue(body)
        self.assertIn("javascript", self.fetch("/static/model.js")[1]["Content-Type"])

    def test_only_known_files(self) -> None:
        for path in (
            "/static/../store.py",
            "/static/%2e%2e/store.py",
            "/static/nope.js",
            "/static/",
        ):
            self.assertEqual(self.fetch(path)[0], 404, path)


class StreamTest(ServerTestCase):
    def setUp(self) -> None:
        super().setUp()
        original = server.STREAM_POLL_S
        server.STREAM_POLL_S = 0.05
        self.addCleanup(setattr, server, "STREAM_POLL_S", original)

    def read_messages(
        self, path: str, count: int, token: str | None = None
    ) -> list[dict[str, Any]]:
        req = urllib.request.Request(self.base + path)
        req.add_header("Authorization", f"Bearer {token or self.viewer}")
        messages: list[dict[str, Any]] = []
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertIn("text/event-stream", resp.headers["Content-Type"])
            data = None
            while len(messages) < count:
                line = resp.readline().decode().rstrip("\n")
                if line.startswith("data: "):
                    data = line[6:]
                elif line == "" and data is not None:
                    messages.append(json.loads(data))
                    data = None
        return messages

    def test_sends_events_after_seq_with_job_state(self) -> None:
        self.call(
            "POST",
            "/events",
            {
                "events": [
                    event(1),
                    event(2, ts="2026-11-02T10:05:00+01:00", frm="build", to="gate"),
                ]
            },
        )
        (msg,) = self.read_messages("/stream?after=1", 1)
        self.assertEqual(msg["event"]["seq"], 2)
        self.assertEqual(msg["job"]["stage"], "gate")
        self.assertEqual(msg["repos"][0]["repo"], "CTDes/textkit")

    def test_delivers_events_posted_while_connected(self) -> None:
        def post_later() -> None:
            threading.Event().wait(0.2)
            self.call("POST", "/events", {"events": [event(7)]})

        threading.Thread(target=post_later, daemon=True).start()
        (msg,) = self.read_messages("/stream?after=0", 1)
        self.assertEqual(msg["event"]["id"], event(7)["id"])

    def test_needs_a_token(self) -> None:
        self.assertEqual(self.call("GET", "/stream", token=None)[0], 401)


if __name__ == "__main__":
    unittest.main()
