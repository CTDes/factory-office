"""factory-office commands: token, state, tail."""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from factory_office import cli, store
from helpers import event, fixture_events


def run(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class CliTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.db = str(Path(tempfile.mkdtemp()) / "office.db")

    def ingest(self, events: list[dict[str, object]]) -> None:
        conn = store.connect(self.db)
        store.ingest(conn, events, "test")
        conn.close()


class TokenCommandTest(CliTestCase):
    def test_add_prints_token_once_and_list_hides_it(self) -> None:
        code, out, err = run("--db", self.db, "token", "add", "mac-1")
        token = out.strip()
        self.assertEqual(code, 0)
        self.assertIn("FACTORY_EVENTS_TOKEN", err)
        code, out, _ = run("--db", self.db, "token", "list")
        self.assertIn("mac-1", out)
        self.assertNotIn(token, out)
        self.assertEqual(run("--db", self.db, "token", "remove", "mac-1")[0], 0)
        self.assertEqual(run("--db", self.db, "token", "remove", "mac-1")[0], 1)
        self.assertEqual(run("--db", self.db, "token", "add")[0], 2)

    def test_view_tokens(self) -> None:
        code, _, err = run("--db", self.db, "token", "add", "alice", "--view")
        self.assertEqual(code, 0)
        self.assertIn("view token for alice", err)
        self.assertIn("view", run("--db", self.db, "token", "list")[1])


class StateCommandTest(CliTestCase):
    def test_groups_active_jobs_by_repo_and_counts_finished(self) -> None:
        self.ingest(
            [
                event(
                    1,
                    job_id="012-a",
                    to="build",
                    job={"title": "Reading time", "round": 2, "risk": "medium"},
                ),
                event(2, job_id="013-b", to="done"),
                event(3, repo="CTDes/factory-sandbox", job_id="003-v", to="ready", job={"pr": 4}),
            ]
        )
        code, out, _ = run("--db", self.db, "state")
        self.assertEqual(code, 0)
        self.assertIn("CTDes/textkit", out)
        self.assertIn("1 active · 1 done", out)
        self.assertIn("build        012-a", out)
        self.assertIn("round 2 · medium", out)
        self.assertIn("Reading time", out)
        self.assertIn("PR #4", out)
        self.assertNotIn("013-b", out)
        self.assertIn("013-b", run("--db", self.db, "state", "--all")[1])

    def test_empty(self) -> None:
        self.assertIn("no events yet", run("--db", self.db, "state")[1])


class TailCommandTest(CliTestCase):
    def test_prints_last_lines_with_transition(self) -> None:
        self.ingest(fixture_events())
        code, out, _ = run("--db", self.db, "tail", "-n", "3")
        lines = out.strip().splitlines()
        self.assertEqual(code, 0)
        self.assertEqual(len(lines), 3)
        self.assertIn("CTDes/factory-sandbox", lines[-1])
        self.assertIn(" → ", lines[-1])

    def test_repo_filter(self) -> None:
        self.ingest([event(1), event(2, repo="other/repo")])
        out = run("--db", self.db, "tail", "--repo", "other/repo")[1]
        self.assertIn("other/repo", out)
        self.assertNotIn("CTDes/textkit", out)


class DefaultDbTest(unittest.TestCase):
    def test_env_wins(self) -> None:
        import os

        old = os.environ.get(cli.DB_ENV)
        os.environ[cli.DB_ENV] = "/tmp/x/office.db"
        try:
            self.assertEqual(cli.default_db(), Path("/tmp/x/office.db"))
        finally:
            if old is None:
                del os.environ[cli.DB_ENV]
            else:
                os.environ[cli.DB_ENV] = old


if __name__ == "__main__":
    unittest.main()
