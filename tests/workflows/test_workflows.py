"""Course checks on the lab workflow files in labs/ (no GitHub, no network)."""

import hashlib
import os
import re
import shutil
import subprocess
import sys

import pytest

from conftest import (LABS, REPO, all_workflow_files, load_workflow, needs_jq, run_bash, step_script)

ENVS = ["dev", "sit", "pre-prod", "prod"]
DEPLOY_JOBS = [f"deploy-{e}" for e in ENVS]
PINNED = {  # the current majors; a workflow that uses another version fails this test on purpose
    "actions/checkout": "v7",
    "actions/setup-python": "v7",
    "actions/upload-artifact": "v7",
    "actions/download-artifact": "v8",
    "hashicorp/setup-terraform": "v4",
}


# ---- every file ---------------------------------------------------------------------------------
def test_there_are_seven_labs_and_no_environment_branch_leftovers():
    assert all_workflow_files() == ["ci.yml", "deliver.yml", "hello.yml", "infra.yml", "python-app.yml", "rollback.yml", "tests.yml"]
    for name in all_workflow_files():
        text = (LABS / name).read_text().lower()
        for word in ("develop", "tree hash", "promotion-path", "release branch", "hotfix/"):
            assert word not in text, f"{name} still mentions {word!r}"


@pytest.mark.parametrize("name", all_workflow_files())
def test_yaml_parses_and_has_jobs(name):
    wf = load_workflow(name)
    assert wf["name"] and wf["jobs"] and wf["on"]


@pytest.mark.parametrize("name", all_workflow_files())
def test_actions_are_pinned_to_current_majors(name):
    text = (LABS / name).read_text()
    for action, version in re.findall(r"uses:\s*([\w./-]+)@(\S+)", text):
        assert PINNED.get(action) == version, f"{name}: {action}@{version}"


@pytest.mark.parametrize("name", all_workflow_files())
def test_every_workflow_starts_read_only(name):
    assert load_workflow(name)["permissions"] == {"contents": "read"}


# ---- CI: a reusable workflow, a stable required-check name --------------------------------------
def test_ci_has_no_path_filter_and_runs_on_every_pull_request():
    on = load_workflow("ci.yml")["on"]
    assert "pull_request" in on
    # `pull_request:` with nothing under it is None: no branches, no paths, no filters at all
    assert not on["pull_request"], "a required check must not hide behind a filter"
    assert on["push"] == {"branches": ["main"]}
    assert "paths" not in on["push"] and "paths-ignore" not in on["push"]


def test_ci_calls_the_reusable_tests_workflow():
    ci, tests = load_workflow("ci.yml"), load_workflow("tests.yml")
    assert list(ci["jobs"]) == ["test"]
    assert ci["jobs"]["test"]["uses"] == "./.github/workflows/tests.yml"
    assert "workflow_call" in tests["on"]
    assert tests["on"]["workflow_call"]["inputs"]["python-version"]["type"] == "string"
    assert list(tests["jobs"]) == ["pytest"]
    assert tests["jobs"]["pytest"]["name"] == "pytest"


def test_the_check_name_is_calling_job_slash_called_job():
    """GitHub names the check '<calling job> / <called job>'. setup_repo.sh must require that string."""
    ci, tests = load_workflow("ci.yml"), load_workflow("tests.yml")
    calling = next(iter(ci["jobs"]))
    called = next(iter(tests["jobs"].values()))["name"]
    context = f"{calling} / {called}"
    assert context == "test / pytest"
    script = (REPO / "scripts" / "setup_repo.sh").read_text()
    assert re.search(rf'^CI_CHECK="{re.escape(context)}"$', script, re.M)


# ---- deliver ------------------------------------------------------------------------------------
def test_deliver_triggers_on_main_and_ignores_infra_and_docs():
    on = load_workflow("deliver.yml")["on"]
    assert on["push"]["branches"] == ["main"]
    assert set(on["push"]["paths-ignore"]) == {"infra/**", "**/*.md"}
    assert "paths" not in on["push"]
    assert "workflow_dispatch" in on


def test_deliver_jobs_chain_in_order_with_their_environments():
    jobs = load_workflow("deliver.yml")["jobs"]
    assert list(jobs) == ["build", *DEPLOY_JOBS, "release"]
    assert jobs["deploy-dev"]["needs"] == "build"
    previous = "deploy-dev"
    for job in DEPLOY_JOBS[1:]:
        assert previous in jobs[job]["needs"], f"{job} must wait for {previous}"
        assert "build" in jobs[job]["needs"]     # each one still reads build's sha256
        previous = job
    for env, job in zip(ENVS, DEPLOY_JOBS):
        assert jobs[job]["environment"] == env
        assert jobs[job]["concurrency"] == {"group": f"deploy-{env}", "cancel-in-progress": False}
        assert jobs[job]["permissions"]["actions"] == "read"


def test_release_comes_only_after_prod_and_alone_may_write():
    jobs = load_workflow("deliver.yml")["jobs"]
    assert "deploy-prod" in jobs["release"]["needs"]
    assert jobs["release"]["permissions"] == {"contents": "write"}
    for name, job in jobs.items():
        if name != "release":
            assert job.get("permissions", {}).get("contents", "read") == "read"
        assert "release" not in (job.get("needs") or [])


def test_build_names_the_artifact_after_the_commit_and_keeps_it_30_days():
    jobs = load_workflow("deliver.yml")["jobs"]
    upload = next(s for s in jobs["build"]["steps"] if "upload-artifact" in s.get("uses", ""))
    assert upload["with"]["name"] == "riskcheck-sha-${{ github.sha }}"
    assert upload["with"]["retention-days"] == 30
    for job in DEPLOY_JOBS:
        download = next(s for s in jobs[job]["steps"] if "download-artifact" in s.get("uses", ""))
        assert download["with"]["name"] == "riskcheck-sha-${{ github.sha }}"


def test_the_four_deploy_jobs_differ_only_in_their_environment():
    jobs = load_workflow("deliver.yml")["jobs"]
    scripts = {step_script(jobs[j], "Deploy") for j in DEPLOY_JOBS}
    assert len(scripts) == 1, "the deploy script must be identical in all four jobs"


def make_artifact(root, content=b"fake wheel"):
    (root / "artifact").mkdir()
    wheel = root / "artifact" / "riskcheck-0.1.0-py3-none-any.whl"
    wheel.write_bytes(content)
    return wheel, hashlib.sha256(content).hexdigest()


def deploy_env(root, env, expected, extra=None):
    summary = root / "summary.md"
    base = {
        "ENV_NAME": env, "APPROVAL": "no", "EXPECTED_SHA256": expected,
        "GITHUB_SHA": "a" * 40, "GITHUB_STEP_SUMMARY": str(summary),
    }
    return {**os.environ, **base, **(extra or {})}, summary


@pytest.mark.parametrize("env", ENVS)
def test_deploy_step_prints_the_sha_and_the_hash_and_writes_a_summary(tmp_path, env):
    wheel, digest = make_artifact(tmp_path)
    environ, summary = deploy_env(tmp_path, env, digest)
    jobs = load_workflow("deliver.yml")["jobs"]
    result = run_bash(step_script(jobs[f"deploy-{env}"], "Deploy"), environ, tmp_path)
    assert result.returncode == 0, result.stderr
    assert f"deploying riskcheck sha-{'a' * 40} to {env}" in result.stdout
    assert f"sha256   : {digest}" in result.stdout
    table = summary.read_text()
    assert f"| {env} |" in table and digest[:12] in table and "| --- |" in table


def test_deploy_step_refuses_a_file_that_is_not_the_one_build_made(tmp_path):
    wheel, digest = make_artifact(tmp_path)
    environ, _ = deploy_env(tmp_path, "dev", "0" * 64)
    result = run_bash(step_script(load_workflow("deliver.yml")["jobs"]["deploy-dev"], "Deploy"), environ, tmp_path)
    assert result.returncode == 1
    assert "Not the file we built" in result.stdout


@needs_jq
def test_release_creates_the_tag_when_it_is_missing(tmp_path, fake_gh):
    (tmp_path / "VERSION").write_text("0.2.0\n")
    environ = fake_gh.env(GITHUB_SHA="b" * 40, GH_REPO="o/r", SHA256="c" * 64, RUN_URL="https://example/run/1",
                          GITHUB_STEP_SUMMARY=str(tmp_path / "s.md"))
    script = step_script(load_workflow("deliver.yml")["jobs"]["release"], "Create the release")
    result = run_bash(script, environ, tmp_path)
    assert result.returncode == 0, result.stderr
    create = [c for c in fake_gh.calls() if c.startswith("gh release create")]
    assert len(create) == 1 and "v0.2.0" in create[0] and f"--target {'b' * 40}" in create[0]
    assert "c" * 64 in create[0] and "https://example/run/1" in create[0] and "b" * 40 in create[0]


@needs_jq
def test_release_does_nothing_when_the_tag_exists(tmp_path, fake_gh):
    (tmp_path / "VERSION").write_text("0.1.0\n")
    fake_gh.answer("repos/o/r/git/ref/tags/v0.1.0", '{"ref": "refs/tags/v0.1.0"}')
    environ = fake_gh.env(GITHUB_SHA="b" * 40, GH_REPO="o/r", SHA256="c" * 64, RUN_URL="x", GITHUB_STEP_SUMMARY=str(tmp_path / "s.md"))
    result = run_bash(step_script(load_workflow("deliver.yml")["jobs"]["release"], "Create the release"), environ, tmp_path)
    assert result.returncode == 0 and "already exists" in result.stdout
    assert not [c for c in fake_gh.calls() if c.startswith("gh release create")]


def test_release_rejects_a_bad_version(tmp_path, fake_gh):
    (tmp_path / "VERSION").write_text("banana\n")
    environ = fake_gh.env(GITHUB_SHA="b" * 40, GH_REPO="o/r", SHA256="c", RUN_URL="x", GITHUB_STEP_SUMMARY=str(tmp_path / "s.md"))
    result = run_bash(step_script(load_workflow("deliver.yml")["jobs"]["release"], "Create the release"), environ, tmp_path)
    assert result.returncode == 1 and "Bad VERSION" in result.stdout


# ---- rollback -----------------------------------------------------------------------------------
def test_rollback_inputs_and_environment():
    wf = load_workflow("rollback.yml")
    inputs = wf["on"]["workflow_dispatch"]["inputs"]
    assert inputs["environment"]["type"] == "choice" and inputs["environment"]["options"] == ENVS
    assert inputs["environment"]["required"] is True
    assert inputs["sha"]["type"] == "string" and inputs["sha"]["required"] is True
    deploy = wf["jobs"]["deploy"]
    assert deploy["needs"] == "find"
    assert deploy["environment"] == "${{ inputs.environment }}"           # the same approvals as a normal deploy
    assert deploy["concurrency"]["group"] == "deploy-${{ inputs.environment }}"   # the same group as deliver.yml
    assert wf["jobs"]["find"]["permissions"]["actions"] == "read"
    assert deploy["permissions"]["actions"] == "read"


@pytest.fixture
def rollback_case(tmp_path, fake_gh):
    sha = "d" * 40
    api = "repos/o/r/actions"
    script = step_script(load_workflow("rollback.yml")["jobs"]["find"], "Find a good build")
    out = tmp_path / "out.txt"

    def go(artifacts, run_name="deliver", build="success", sha_in=sha):
        fake_gh.answer(f"{api}/artifacts?name=riskcheck-sha-{sha}&per_page=100", artifacts)
        fake_gh.answer(f"{api}/runs/11", f'{{"name": "{run_name}"}}')
        fake_gh.answer(f"{api}/runs/11/jobs?per_page=100",
                       f'{{"jobs": [{{"name": "build", "conclusion": "{build}"}}, {{"name": "deploy-prod", "conclusion": null}}]}}')
        environ = fake_gh.env(GH_REPO="o/r", SHA=sha_in, GITHUB_OUTPUT=str(out))
        result = run_bash(script, environ, tmp_path)
        return result, (out.read_text() if out.exists() else "")
    return go


def art(expired=False, branch="main", run_id=11):
    return ('{"artifacts": [{"expired": %s, "workflow_run": {"id": %d, "head_branch": "%s"}}]}'
            % (str(expired).lower(), run_id, branch))


@needs_jq
def test_rollback_finds_a_good_build_even_if_the_run_is_still_waiting_for_prod(rollback_case):
    # the run is not finished (deploy-prod conclusion is null) but its build job succeeded
    result, out = rollback_case(art())
    assert result.returncode == 0, result.stdout + result.stderr
    assert "run_id=11" in out


@needs_jq
@pytest.mark.parametrize("label,kwargs,artifacts", [
    ("expired", {}, art(expired=True)),
    ("not main", {}, art(branch="feature/x")),
    ("build failed", {"build": "failure"}, art()),
    ("another workflow", {"run_name": "ci"}, art()),
    ("no artifact", {}, '{"artifacts": []}'),
])
def test_rollback_fails_clearly_when_there_is_no_good_build(rollback_case, label, kwargs, artifacts):
    result, out = rollback_case(artifacts, **kwargs)
    assert result.returncode == 1, label
    assert "No build to roll back to" in result.stdout and out == ""


@pytest.mark.parametrize("bad", ["", "abc", "D" * 40, "g" * 40, "d" * 39])
def test_rollback_rejects_a_sha_that_is_not_40_lowercase_hex(rollback_case, bad):
    result, _ = rollback_case('{"artifacts": []}', sha_in=bad)
    assert result.returncode == 1 and "Not a full commit hash" in result.stdout


def test_rollback_deploy_step_prints_the_old_sha(tmp_path):
    wheel, digest = make_artifact(tmp_path)
    summary = tmp_path / "s.md"
    environ = {**os.environ, "ENV_NAME": "prod", "SHA": "e" * 40, "GITHUB_ACTOR": "me", "GITHUB_STEP_SUMMARY": str(summary)}
    result = run_bash(step_script(load_workflow("rollback.yml")["jobs"]["deploy"], "Deploy"), environ, tmp_path)
    assert result.returncode == 0, result.stderr
    assert f"deploying riskcheck sha-{'e' * 40} to prod" in result.stdout and digest in result.stdout
    assert "ROLLBACK" in result.stdout and "Rollback of prod" in summary.read_text()


# ---- infra: its own pipeline --------------------------------------------------------------------
def test_infra_and_deliver_split_the_repo_by_path():
    infra, deliver = load_workflow("infra.yml")["on"], load_workflow("deliver.yml")["on"]
    assert infra["pull_request"]["paths"] == ["infra/**"]
    assert infra["push"]["paths"] == ["infra/**"] and infra["push"]["branches"] == ["main"]
    assert "infra/**" in deliver["push"]["paths-ignore"]


def test_infra_plans_every_environment_on_a_pull_request_and_applies_in_order_on_push():
    jobs = load_workflow("infra.yml")["jobs"]
    assert jobs["plan"]["strategy"]["matrix"]["env"] == ENVS
    assert jobs["plan"]["if"] == "github.event_name == 'pull_request'"
    chain = ["apply-dev", "apply-sit", "apply-pre-prod", "apply-prod"]
    assert jobs["apply-dev"]["if"] == "github.event_name == 'push'"
    for env, name, before in zip(ENVS, chain, [None] + chain[:-1]):
        assert jobs[name]["environment"] == env
        if before:
            assert jobs[name]["needs"] == before
    assert {f"{e}.tfvars" for e in ENVS} == {p.name for p in (REPO / "infra" / "envs").glob("*.tfvars")}


def test_infra_is_not_the_required_check():
    script = (REPO / "scripts" / "setup_repo.sh").read_text()
    assert 'CI_CHECK="test / pytest"' in script and "infra" not in script.split("CI_CHECK=")[1].splitlines()[0]


# ---- the repo itself ----------------------------------------------------------------------------
def test_version_file_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", (REPO / "VERSION").read_text().strip())


def test_default_pytest_run_is_still_the_eight_score_tests():
    r = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
                       cwd=REPO, capture_output=True, text=True)
    assert "8 tests collected" in r.stdout, r.stdout


def test_the_wheel_takes_its_version_from_the_version_file(tmp_path):
    pytest.importorskip("setuptools")
    work = tmp_path / "copy"
    shutil.copytree(REPO, work, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".venv", ".terraform"))
    (work / "VERSION").write_text("9.8.7\n")
    r = subprocess.run([sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "--no-build-isolation", "-w", "dist", "-q"],
                       cwd=work, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert [p.name for p in (work / "dist").glob("*.whl")] == ["riskcheck-9.8.7-py3-none-any.whl"]
