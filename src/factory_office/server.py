"""HTTP collector and office: events in from the factories, state and a live stream out.

Standard library only (ThreadingHTTPServer). Every request opens its own SQLite connection, so
handlers share nothing but the database file.

Every data route needs the office token (``Authorization: Bearer <token>``); there is one.

  GET  /                                     the office page (it asks for the token)
  GET  /static/<file>                        the page's scripts and styles
  GET  /health                               {"ok": true}
  POST /events   {"events": [...]}           {"accepted": n, "duplicates": m}; an empty batch
                                             is how a factory checks its link
  GET  /state                                repos, every job, last seq
  GET  /events?after=&limit=&last=&repo=&job_id=   events in arrival order
  GET  /stream?after=SEQ                     Server-Sent Events, one per new event
"""

from __future__ import annotations

import json
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from factory_office import store

MAX_BODY = 8 * 1024 * 1024
MAX_BATCH = 1000
STREAM_POLL_S = 1.0
STREAM_PING_S = 15.0
SENDER = "office-token"  # recorded per event; one token means no per-machine identity

_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
}
_CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


def _web_files() -> dict[str, tuple[bytes, str]]:
    """The page's files, read once: published name -> (bytes, content type)."""
    files: dict[str, tuple[bytes, str]] = {}
    root = resources.files("factory_office") / "web"
    for entry in root.iterdir():
        suffix = Path(entry.name).suffix
        if entry.is_file() and suffix in _TYPES:
            files[entry.name] = (entry.read_bytes(), _TYPES[suffix])
    return files


class OfficeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], db_path: Path, quiet: bool = True) -> None:
        self.db_path = db_path
        self.quiet = quiet
        self.stopping = threading.Event()
        self.web = _web_files()
        conn = store.connect(db_path)  # create or migrate the schema before the first request
        try:
            store.office_token(conn)
        finally:
            conn.close()
        super().__init__(address, Handler)

    def server_close(self) -> None:
        self.stopping.set()
        super().server_close()


class Handler(BaseHTTPRequestHandler):
    server: OfficeServer
    server_version = "factory-office/0.3.0"

    # ------------------------------------------------------------ plumbing

    def _headers(self, status: HTTPStatus, ctype: str, length: int | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")

    def _send(self, status: HTTPStatus, body: Any, extra: dict[str, str] | None = None) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(data))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def _error(self, status: HTTPStatus, message: str, **extra: Any) -> None:
        headers = {"WWW-Authenticate": "Bearer"} if status == HTTPStatus.UNAUTHORIZED else None
        self._send(status, {"error": message, **extra}, headers)

    def _token(self) -> bool:
        """True when the caller sent the office token; otherwise answers 401 and returns False."""
        header = self.headers.get("Authorization", "")
        raw = header[7:].strip() if header.lower().startswith("bearer ") else ""
        conn = store.connect(self.server.db_path)
        try:
            ok = store.check_token(conn, raw)
        finally:
            conn.close()
        if not ok:
            self._error(HTTPStatus.UNAUTHORIZED, "missing or wrong office token")
        return ok

    def log_message(self, format: str, *args: Any) -> None:
        if not self.server.quiet:
            super().log_message(format, *args)

    # ------------------------------------------------------------ routes

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        if url.path == "/health":
            self._send(HTTPStatus.OK, {"ok": True})
        elif url.path == "/":
            self._static("index.html")
        elif url.path.startswith("/static/"):
            self._static(url.path[len("/static/") :])
        elif url.path == "/state":
            if self._token():
                conn = store.connect(self.server.db_path)
                try:
                    self._send(HTTPStatus.OK, store.state(conn))
                finally:
                    conn.close()
        elif url.path == "/events":
            if self._token():
                self._events(query)
        elif url.path == "/stream":
            if self._token():
                self._stream(query)
        else:
            self._error(HTTPStatus.NOT_FOUND, f"no route {url.path}")

    def _static(self, name: str) -> None:
        found = self.server.web.get(name)  # exact names only: no paths, no traversal
        if found is None:
            self._error(HTTPStatus.NOT_FOUND, f"no file {name}")
            return
        data, ctype = found
        self._headers(HTTPStatus.OK, ctype, len(data))
        if ctype.startswith("text/html"):
            self.send_header("Content-Security-Policy", _CSP)
        self.end_headers()
        self.wfile.write(data)

    @staticmethod
    def _int(query: dict[str, list[str]], key: str, default: int) -> int:
        return int(query.get(key, [str(default)])[0])

    def _events(self, query: dict[str, list[str]]) -> None:
        try:
            after = self._int(query, "after", 0)
            limit = self._int(query, "limit", 500)
            last = self._int(query, "last", 0)
        except ValueError:
            self._error(HTTPStatus.BAD_REQUEST, "'after', 'limit' and 'last' must be integers")
            return
        repo = query.get("repo", [None])[0]
        job_id = query.get("job_id", [None])[0]
        conn = store.connect(self.server.db_path)
        try:
            if last > 0:
                rows = store.last_events(conn, last, repo, job_id)
            else:
                rows = store.events_after(conn, after, limit, repo, job_id)
            self._send(HTTPStatus.OK, {"events": rows})
        finally:
            conn.close()

    def _stream(self, query: dict[str, list[str]]) -> None:
        """One SSE message per new event: the event plus its job's and repo's new state."""
        try:
            after = self._int(query, "after", 0)
        except ValueError:
            self._error(HTTPStatus.BAD_REQUEST, "'after' must be an integer")
            return
        if "Last-Event-ID" in self.headers:
            try:
                after = max(after, int(self.headers["Last-Event-ID"]))
            except ValueError:
                pass
        self._headers(HTTPStatus.OK, "text/event-stream; charset=utf-8")
        self.end_headers()
        conn = store.connect(self.server.db_path)
        quiet_since = time.monotonic()
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while not self.server.stopping.is_set():
                rows = store.events_after(conn, after, 200)
                for row in rows:
                    payload = {
                        "event": row,
                        "job": store.job_state(conn, row["repo"], row["job_id"]),
                        "repos": store.repo_state(conn, row["repo"]),
                    }
                    message = (
                        f"id: {row['seq']}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    )
                    self.wfile.write(message.encode("utf-8"))
                    after = row["seq"]
                if rows:
                    quiet_since = time.monotonic()
                elif time.monotonic() - quiet_since >= STREAM_PING_S:
                    self.wfile.write(b": ping\n\n")
                    quiet_since = time.monotonic()
                self.wfile.flush()
                self.server.stopping.wait(STREAM_POLL_S)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            conn.close()

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/events":
            self._error(HTTPStatus.NOT_FOUND, f"no route {self.path}")
            return
        if not self._token():
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
            result = store.ingest(conn, batch, SENDER)
        except store.InvalidEvent as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc), index=exc.index)
            return
        finally:
            conn.close()
        self._send(HTTPStatus.OK, {"accepted": result.accepted, "duplicates": result.duplicates})


def make_server(db_path: Path, host: str = "127.0.0.1", port: int = 8765) -> OfficeServer:
    return OfficeServer((host, port), db_path)
