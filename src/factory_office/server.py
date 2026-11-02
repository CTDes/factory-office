"""HTTP collector: POST /events from the factories, GET /state and /events for viewers.

Standard library only (ThreadingHTTPServer). Every request opens its own SQLite connection, so
handlers share nothing but the database file.

  GET  /health                      no auth; {"ok": true}
  POST /events   {"events": [...]}  token; 200 {"accepted": n, "duplicates": m}
  GET  /state                       token; repos and the latest state of every job
  GET  /events?after=SEQ&limit=N    token; events in arrival order, for viewers and tail
"""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from factory_office import store

MAX_BODY = 8 * 1024 * 1024
MAX_BATCH = 1000


class OfficeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], db_path: Path, quiet: bool = True) -> None:
        self.db_path = db_path
        self.quiet = quiet
        store.connect(db_path).close()  # create the schema before the first request
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server: OfficeServer
    server_version = "factory-office/0.1"

    # ------------------------------------------------------------ plumbing

    def _send(self, status: HTTPStatus, body: Any, headers: dict[str, str] | None = None) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def _error(self, status: HTTPStatus, message: str, **extra: Any) -> None:
        headers = {"WWW-Authenticate": "Bearer"} if status == HTTPStatus.UNAUTHORIZED else None
        self._send(status, {"error": message, **extra}, headers)

    def _machine(self) -> str | None:
        """The machine behind the bearer token, or None after answering 401."""
        header = self.headers.get("Authorization", "")
        token = header[7:].strip() if header.lower().startswith("bearer ") else ""
        conn = store.connect(self.server.db_path)
        try:
            machine = store.check_token(conn, token)
        finally:
            conn.close()
        if machine is None:
            self._error(HTTPStatus.UNAUTHORIZED, "missing or unknown token")
        return machine

    def log_message(self, format: str, *args: Any) -> None:
        if not self.server.quiet:
            super().log_message(format, *args)

    # ------------------------------------------------------------ routes

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        if url.path == "/health":
            self._send(HTTPStatus.OK, {"ok": True})
            return
        if url.path not in ("/state", "/events"):
            self._error(HTTPStatus.NOT_FOUND, f"no route {url.path}")
            return
        if self._machine() is None:
            return
        conn = store.connect(self.server.db_path)
        try:
            if url.path == "/state":
                self._send(HTTPStatus.OK, store.state(conn))
                return
            query = parse_qs(url.query)
            try:
                after = int(query.get("after", ["0"])[0])
                limit = int(query.get("limit", ["500"])[0])
            except ValueError:
                self._error(HTTPStatus.BAD_REQUEST, "'after' and 'limit' must be integers")
                return
            repo = query.get("repo", [None])[0]
            self._send(HTTPStatus.OK, {"events": store.events_after(conn, after, limit, repo)})
        finally:
            conn.close()

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/events":
            self._error(HTTPStatus.NOT_FOUND, f"no route {self.path}")
            return
        sender = self._machine()
        if sender is None:
            return
        length_header = self.headers.get("Content-Length")
        if length_header is None:
            self._error(HTTPStatus.LENGTH_REQUIRED, "Content-Length is required")
            return
        try:
            length = int(length_header)
        except ValueError:
            self._error(HTTPStatus.BAD_REQUEST, "invalid Content-Length")
            return
        if length > MAX_BODY:
            self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, f"body over {MAX_BODY} bytes")
            return
        try:
            body = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._error(HTTPStatus.BAD_REQUEST, "body is not valid JSON")
            return
        batch = body.get("events") if isinstance(body, dict) else None
        if not isinstance(batch, list):
            self._error(HTTPStatus.BAD_REQUEST, 'body must be {"events": [...]}')
            return
        if len(batch) > MAX_BATCH:
            self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, f"more than {MAX_BATCH} events")
            return
        conn = store.connect(self.server.db_path)
        try:
            result = store.ingest(conn, batch, sender)
        except store.InvalidEvent as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc), index=exc.index)
            return
        finally:
            conn.close()
        self._send(HTTPStatus.OK, {"accepted": result.accepted, "duplicates": result.duplicates})


def make_server(db_path: Path, host: str = "127.0.0.1", port: int = 8765) -> OfficeServer:
    return OfficeServer((host, port), db_path)
