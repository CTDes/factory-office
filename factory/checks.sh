#!/usr/bin/env bash
# Checks for factory-office. Same contract as the software factory's checks.sh:
# non-interactive, installs deps on a fresh worktree, runs lint + typecheck + tests + build,
# never rewrites tracked files, exits non-zero on any failure.
#
# Runs against the CURRENT WORKING DIRECTORY (the gate runs the copy from origin/main
# with the job's worktree as cwd), not against the directory this script lives in.
set -euo pipefail

# Never reuse bytecode: same-size edits within one second can otherwise run a stale .pyc.
export PYTHONDONTWRITEBYTECODE=1
PYTHON="${PYTHON:-python3}"
VENV=".venv"
STAMP="$VENV/.requirements.sha256"

step() { printf '\n==> %s\n' "$*"; }

step "dependencies"
want="$(shasum -a 256 requirements-dev.txt | cut -d' ' -f1)"
if [[ ! -x "$VENV/bin/python" || "$(cat "$STAMP" 2>/dev/null || true)" != "$want" ]]; then
  "$PYTHON" -m venv "$VENV"
  "$VENV/bin/python" -m pip install --quiet --disable-pip-version-check -r requirements-dev.txt
  echo "$want" > "$STAMP"
else
  echo "up to date"
fi
PY="$VENV/bin/python"

step "lint"
"$PY" -m ruff check --no-fix .
"$PY" -m ruff format --check .

step "typecheck"
"$PY" -m mypy

step "tests"
PYTHONPATH=src "$PY" -m unittest discover -s tests -v

step "tests (web model)"
if command -v node >/dev/null 2>&1; then
  node --test tests/js/*.test.js
else
  echo "node not found: skipping the JavaScript model tests (CI runs them)"
fi

step "build"
out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT
"$PY" -m pip wheel --quiet --disable-pip-version-check --no-deps --no-build-isolation -w "$out" . >/dev/null
ls "$out"

step "ok"
