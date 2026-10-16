"""infra/: a terraform_data stack. Run in a temp copy (never inside your project folder)."""

import json
import os
import shutil
import subprocess

import pytest

from conftest import REPO, needs_terraform

ENVS = ["dev", "sit", "pre-prod", "prod"]
pytestmark = needs_terraform


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    work = tmp_path_factory.mktemp("infra") / "infra"
    shutil.copytree(REPO / "infra", work)
    cache = os.path.expanduser("~/.terraform.d/plugin-cache")
    env = {**os.environ, "TF_IN_AUTOMATION": "1", "TF_INPUT": "0"}
    if os.path.isdir(cache):
        env["TF_PLUGIN_CACHE_DIR"] = cache

    def tf(*args):
        return subprocess.run(["terraform", *args], cwd=work, env=env, capture_output=True, text=True)

    r = tf("init", "-input=false")
    assert r.returncode == 0, r.stdout + r.stderr
    return tf


def test_format_and_validate(stack):
    assert stack("fmt", "-check", "-recursive").returncode == 0
    assert stack("validate").returncode == 0


@pytest.mark.parametrize("env", ENVS)
def test_plan_each_environment_creates_exactly_one_resource_with_its_own_settings(stack, env):
    assert stack("plan", f"-var-file=envs/{env}.tfvars", "-out=tfplan").returncode == 0
    shown = json.loads(stack("show", "-json", "tfplan").stdout)
    changes = shown["resource_changes"]
    assert [c["address"] for c in changes] == ["terraform_data.settings"]
    assert changes[0]["change"]["actions"] == ["create"]
    assert changes[0]["change"]["after"]["input"]["env"] == env


def test_a_misspelled_environment_stops_before_any_plan(stack):
    r = stack("plan", "-var", "env=staging")
    assert r.returncode != 0 and "env must be one of" in (r.stdout + r.stderr)


def test_apply_and_destroy_work_without_any_cloud(stack):
    assert stack("apply", "-auto-approve", "-var-file=envs/dev.tfvars").returncode == 0
    assert stack("output", "-raw", "name").stdout == "finrisk-dev"
    assert stack("destroy", "-auto-approve", "-var-file=envs/dev.tfvars").returncode == 0
