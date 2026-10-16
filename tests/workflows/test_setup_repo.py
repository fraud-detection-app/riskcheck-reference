"""scripts/setup_repo.sh, run against a FAKE gh: it prints every call and sends nothing anywhere."""

import json
import re

import pytest

from conftest import REPO, needs_jq, run_bash

SCRIPT = REPO / "scripts" / "setup_repo.sh"


def setup_fake(fake_gh, existing=False):
    fake_gh.answer("user", '{"id": 4242, "login": "student"}')
    fake_gh.answer("repos/o/r", '{"default_branch": "main"}')
    fake_gh.answer("repos/o/r/rulesets", '[{"id": 77, "name": "protect-main"}, {"id": 5, "name": "other"}]' if existing else "[]")
    for env in ("dev", "sit", "pre-prod", "prod"):
        fake_gh.answer(f"repos/o/r/environments/{env}/deployment-branch-policies",
                       '{"branch_policies": [{"name": "main"}]}' if existing else '{"branch_policies": []}')


def run_setup(fake_gh, tmp_path, *args):
    return run_bash(f'bash "{SCRIPT}" o/r {" ".join(args)}', fake_gh.env(), tmp_path)


def sent(fake_gh):
    """[(METHOD, PATH, body-as-dict)] for every request that carried a JSON body."""
    found = re.findall(r"### (\w+) (\S+)\n(.*?)(?=\n### |\Z)", fake_gh.bodies(), re.S)
    return [(m, p, json.loads(b)) for m, p, b in found]


def ruleset(requests):
    return next(b for m, p, b in requests if p.endswith("/rulesets") or "/rulesets/" in p)


@needs_jq
def test_checks_none_requires_no_status_check(fake_gh, tmp_path):
    setup_fake(fake_gh)
    r = run_setup(fake_gh, tmp_path, "--checks none")
    assert r.returncode == 0, r.stderr
    rs = ruleset(sent(fake_gh))
    kinds = [x["type"] for x in rs["rules"]]
    assert kinds == ["deletion", "non_fast_forward", "pull_request"]
    assert rs["rules"][2]["parameters"]["allowed_merge_methods"] == ["squash", "merge"]
    assert rs["conditions"]["ref_name"]["include"] == ["refs/heads/main"] and rs["bypass_actors"] == []


@needs_jq
def test_checks_ci_requires_exactly_the_check_name_the_workflows_produce(fake_gh, tmp_path):
    setup_fake(fake_gh)
    r = run_setup(fake_gh, tmp_path, "--checks ci")
    assert r.returncode == 0, r.stderr
    rs = ruleset(sent(fake_gh))
    required = [x for x in rs["rules"] if x["type"] == "required_status_checks"]
    assert len(required) == 1
    assert required[0]["parameters"]["required_status_checks"] == [{"context": "test / pytest"}]


@needs_jq
def test_four_environments_main_only_and_reviewers_for_pre_prod_and_prod(fake_gh, tmp_path):
    setup_fake(fake_gh)
    assert run_setup(fake_gh, tmp_path).returncode == 0
    requests = sent(fake_gh)
    envs = {p.rsplit("/", 1)[1]: b for m, p, b in requests if m == "PUT" and "/environments/" in p}
    assert list(envs) == ["dev", "sit", "pre-prod", "prod"]
    for name, body in envs.items():
        assert body["deployment_branch_policy"] == {"protected_branches": False, "custom_branch_policies": True}
        wants_reviewer = name in ("pre-prod", "prod")
        assert body["reviewers"] == ([{"type": "User", "id": 4242}] if wants_reviewer else [])
    rules = [(p, b) for m, p, b in requests if m == "POST" and p.endswith("deployment-branch-policies")]
    assert len(rules) == 4 and all(b == {"name": "main", "type": "branch"} for p, b in rules)
    settings = next(b for m, p, b in requests if m == "PATCH")
    assert settings["allow_squash_merge"] and settings["allow_merge_commit"] and not settings["allow_rebase_merge"]


@needs_jq
def test_running_it_again_updates_instead_of_creating(fake_gh, tmp_path):
    setup_fake(fake_gh, existing=True)
    r = run_setup(fake_gh, tmp_path, "--checks ci")
    assert r.returncode == 0, r.stderr
    requests = sent(fake_gh)
    assert [p for m, p, b in requests if m == "PUT" and "/rulesets/" in p] == ["repos/o/r/rulesets/77"]   # protect-main only, not "other"
    assert not [1 for m, p, b in requests if m == "POST"]          # no second ruleset, no second branch rule
    assert "already exists - skipped" in r.stdout


@needs_jq
def test_it_prints_every_gh_call_and_dry_run_sends_nothing(fake_gh, tmp_path):
    setup_fake(fake_gh)
    r = run_setup(fake_gh, tmp_path, "--dry-run")
    assert r.returncode == 0, r.stderr
    assert "+ gh api user --jq .id" in r.stderr
    assert "+ gh api -X PUT repos/o/r/environments/prod --input -" in r.stderr
    assert "(dry run: not sent)" in r.stderr
    assert sent(fake_gh) == []


@pytest.mark.parametrize("args", ["", "o/r --checks all", "o/r --checks", "o/r extra"])
def test_bad_arguments_are_refused(fake_gh, tmp_path, args):
    r = run_bash(f'bash "{SCRIPT}" {args}', fake_gh.env(), tmp_path)
    assert r.returncode != 0
