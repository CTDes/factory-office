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
    def test_shows_the_same_token_until_rotated(self) -> None:
        code, out, _ = run("--db", self.db, "token")
        token = out.strip()
        self.assertEqual(code, 0)
        self.assertEqual(run("--db", self.db, "token")[1].strip(), token)
        code, out, err = run("--db", self.db, "token", "--rotate")
        self.assertEqual(code, 0)
        self.assertNotEqual(out.strip(), token)
        self.assertIn("link again", err)
        self.assertEqual(run("--db", self.db, "token")[1].strip(), out.strip())


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
