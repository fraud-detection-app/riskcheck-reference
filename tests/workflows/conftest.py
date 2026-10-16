"""Shared helpers for the course checks on the workflow files.

Run them with:   python -m pytest tests/workflows -o addopts=""
(The default `python -m pytest -q` runs only the 8 score tests; see pyproject.toml.)

Nothing here talks to GitHub or to any cloud. The scripts inside the workflows are run on your
laptop with a FAKE `gh` (a tiny shell script that answers from files) and a fake artifact.
"""

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
LABS = REPO / "labs"

# The fake gh answers `gh api <path> [--jq expr]` from <FAKE_GH_DIR>/<path with / ? = & as _>.json,
# using jq for --jq, exits 1 (= HTTP 404) when there is no such file, and logs every call.
FAKE_GH = r"""#!/usr/bin/env bash
echo "gh $*" | tr '\n' ' ' >> "$FAKE_GH_DIR/calls.log"; echo >> "$FAKE_GH_DIR/calls.log"
if [ "$1" != api ]; then exit 0; fi          # gh release create, gh run ... : just log it
shift
path=""; jqx=""; method=GET; has_input=no
while [ $# -gt 0 ]; do
  case "$1" in
    -X) method="$2"; shift ;;
    --jq) jqx="$2"; shift ;;
    --input) has_input=yes; shift ;;
    -f|-F) shift ;;
    -*) ;;
    *) path="$1" ;;
  esac
  shift
done
if [ "$has_input" = yes ]; then
  { printf '### %s %s\n' "$method" "$path"; cat; printf '\n'; } >> "$FAKE_GH_DIR/bodies.log"
fi
if [ "$method" != GET ]; then exit 0; fi
key=$(printf '%s' "$path" | tr '/?=&' '____')
file="$FAKE_GH_DIR/$key.json"
[ -f "$file" ] || exit 1
if [ -n "$jqx" ]; then jq -r "$jqx" "$file"; else cat "$file"; fi
"""


def load_workflow(name: str) -> dict:
    data = yaml.safe_load((LABS / name).read_text())
    # YAML 1.1 reads the key `on` as the boolean True; put it back under "on".
    if True in data:
        data["on"] = data.pop(True)
    return data


def all_workflow_files() -> list[str]:
    return sorted(p.name for p in LABS.glob("*.yml"))


def step_script(job: dict, step_name: str) -> str:
    for step in job["steps"]:
        if step.get("name", "").startswith(step_name):
            return step["run"]
    raise KeyError(step_name)


@pytest.fixture
def fake_gh(tmp_path):
    """A directory with a fake `gh` first on PATH. Put canned answers in it with fake.answer()."""
    directory = tmp_path / "fakegh"
    directory.mkdir()
    gh = directory / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(gh.stat().st_mode | stat.S_IXUSR)

    class Fake:
        dir = directory

        @staticmethod
        def answer(path: str, text: str) -> None:
            key = re.sub(r"[/?=&]", "_", path)
            (directory / f"{key}.json").write_text(text)

        @staticmethod
        def calls() -> list[str]:
            log = directory / "calls.log"
            return log.read_text().splitlines() if log.exists() else []

        @staticmethod
        def bodies() -> str:
            log = directory / "bodies.log"
            return log.read_text() if log.exists() else ""

        @staticmethod
        def env(**extra) -> dict:
            env = {**os.environ, "PATH": f"{directory}{os.pathsep}{os.environ['PATH']}", "FAKE_GH_DIR": str(directory)}
            env.update(extra)
            return env

    return Fake


def run_bash(script: str, env: dict, cwd: Path) -> subprocess.CompletedProcess:
    """Run a workflow `run:` script the way the runner does: bash -e, one process."""
    return subprocess.run(["bash", "-eo", "pipefail", "-c", script], env=env, cwd=cwd, capture_output=True, text=True)


needs_jq = pytest.mark.skipif(shutil.which("jq") is None, reason="jq is not installed (the fake gh uses it)")
needs_terraform = pytest.mark.skipif(shutil.which("terraform") is None, reason="terraform is not installed")
