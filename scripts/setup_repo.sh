#!/usr/bin/env bash
# setup_repo.sh - instructor helper for the practice repo.
#
# Usage:  scripts/setup_repo.sh <owner>/<repo> [--checks none|ci] [--dry-run]
#
# What it does (safe to run again - it updates what exists):
#   1. repo settings: pull requests may be merged by "squash" or "merge commit" (no rebase);
#      the feature branch is deleted after the merge
#   2. creates the four Environments dev, sit, pre-prod, prod, each limited to the default
#      branch (main) only; pre-prod and prod need a reviewer (you, the person running this)
#   3. creates the ruleset "protect-main": changes reach main only through a pull request,
#      no force-push, no deletion, and (with --checks ci) the check "test / pytest" must be green
#
# --checks says which status checks the ruleset REQUIRES. A required check that no workflow
# reports blocks every pull request forever, so match it to the class lab:
#   --checks none : lab 1 (the repo has no workflow yet; the default)
#   --checks ci   : lab 4 (the moment a red "test / pytest" check starts blocking the merge)
# Re-run it at each step - it updates what exists.
#
# --dry-run prints every request that would CHANGE something, and sends none of them.
#
# Needs: the gh CLI, logged in as someone with admin rights on the repo, and a repo that already
# has a first commit on its default branch. Every gh command is printed before it runs.

set -euo pipefail

usage() {
  sed -n '2,23p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-1}"
}

# The check name GitHub reports for ci.yml's job `test`, which calls tests.yml's job `pytest`:
# "<calling job> / <called job>". If you rename either job, change this line.
CI_CHECK="test / pytest"

REPO=""
CHECKS=none
DRY_RUN=false
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage 0 ;;
    --dry-run) DRY_RUN=true ;;
    --checks) shift; CHECKS="${1:-}" ;;
    --checks=*) CHECKS="${1#--checks=}" ;;
    -*) echo "unknown option: $1" >&2; usage ;;
    *) if [ -z "$REPO" ]; then REPO="$1"; else usage; fi ;;
  esac
  shift
done
case "$REPO" in */*) ;; *) echo "give the repo as <owner>/<repo>" >&2; usage ;; esac
case "$CHECKS" in none|ci) ;; *) echo "--checks must be none or ci" >&2; usage ;; esac

# ---- small helpers ---------------------------------------------------------
say() { printf '\n== %s\n' "$*"; }

# print a command in copy-paste form (to stderr, so $(...) never captures it)
show() { { printf '+'; printf ' %q' "$@"; printf '\n'; } >&2; }

# run a gh command that only READS, and show its output
ghx() { show gh "$@"; gh "$@"; }

# gh api with a JSON body read from stdin:  gh_json METHOD PATH <<JSON ... JSON
gh_json() {
  local method="$1" path="$2" body
  body="$(cat)"
  printf '+ gh api -X %s %s --input - <<JSON\n%s\nJSON\n' "$method" "$path" "$body" >&2
  if [ "$DRY_RUN" = true ]; then
    echo "  (dry run: not sent)" >&2
    return 0
  fi
  printf '%s\n' "$body" | gh api -X "$method" "$path" --input - >/dev/null
}

# ---- 0. who are we, which branch is the default? ---------------------------
say "Checking $REPO"
ME_ID="$(ghx api user --jq .id)"
ME_LOGIN="$(ghx api user --jq .login)"
echo "authenticated as $ME_LOGIN (id $ME_ID) - this user will review pre-prod and prod"
DEFAULT_BRANCH="$(ghx api "repos/$REPO" --jq .default_branch)"
echo "default branch: $DEFAULT_BRANCH"

# ---- 1. repo settings ------------------------------------------------------
say "Merge methods: squash and merge commit; delete the branch after the merge"
gh_json PATCH "repos/$REPO" <<JSON
{
  "allow_squash_merge": true,
  "allow_merge_commit": true,
  "allow_rebase_merge": false,
  "delete_branch_on_merge": true
}
JSON

# ---- 2. environments -------------------------------------------------------
# environment name : needs a reviewer?
ENVIRONMENTS="dev:no sit:no pre-prod:yes prod:yes"

for spec in $ENVIRONMENTS; do
  env_name="${spec%%:*}"; review="${spec#*:}"
  say "Environment $env_name (deploys from $DEFAULT_BRANCH only; reviewer: $review)"

  if [ "$review" = yes ]; then
    reviewers="[{\"type\": \"User\", \"id\": $ME_ID}]"
  else
    reviewers="[]"
  fi

  # PUT creates the environment, or updates it if it already exists.
  # prevent_self_review=false: in a one-person org you must be allowed to approve your own deploy.
  gh_json PUT "repos/$REPO/environments/$env_name" <<JSON
{
  "wait_timer": 0,
  "prevent_self_review": false,
  "reviewers": $reviewers,
  "deployment_branch_policy": {
    "protected_branches": false,
    "custom_branch_policies": true
  }
}
JSON

  # the branch rule: only the default branch may deploy here
  # (a brand-new environment may not exist yet in a dry run: then the list is simply empty)
  existing="$(ghx api "repos/$REPO/environments/$env_name/deployment-branch-policies" --jq '.branch_policies[].name' 2>/dev/null || true)"
  if printf '%s\n' "$existing" | grep -qx "$DEFAULT_BRANCH"; then
    echo "  branch rule '$DEFAULT_BRANCH' already exists - skipped"
  else
    gh_json POST "repos/$REPO/environments/$env_name/deployment-branch-policies" <<JSON
{
  "name": "$DEFAULT_BRANCH",
  "type": "branch"
}
JSON
  fi
done

# ---- 3. the ruleset --------------------------------------------------------
CI_RULE=""
if [ "$CHECKS" = ci ]; then
  CI_RULE=',
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": false,
        "required_status_checks": [ { "context": "'"$CI_CHECK"'" } ]
      }
    }'
fi

say "Ruleset protect-main: $DEFAULT_BRANCH needs a pull request, no force-push, no deletion${CI_RULE:+, and the check '$CI_CHECK'}"
BODY="$(cat <<JSON
{
  "name": "protect-main",
  "target": "branch",
  "enforcement": "active",
  "bypass_actors": [],
  "conditions": {
    "ref_name": {
      "include": ["refs/heads/$DEFAULT_BRANCH"],
      "exclude": []
    }
  },
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": false,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false,
        "allowed_merge_methods": ["squash", "merge"]
      }
    }$CI_RULE
  ]
}
JSON
)"
# create the ruleset with this name, or update it if it exists (so re-running is safe)
ruleset_id="$(ghx api "repos/$REPO/rulesets" --jq '.[] | select(.name == "protect-main") | .id')"
if [ -n "$ruleset_id" ]; then
  echo "  ruleset 'protect-main' exists (id $ruleset_id) - updating it"
  printf '%s\n' "$BODY" | gh_json PUT "repos/$REPO/rulesets/$ruleset_id"
else
  printf '%s\n' "$BODY" | gh_json POST "repos/$REPO/rulesets"
fi

if [ "$CHECKS" = none ]; then
  echo
  echo "(--checks none: no check is required yet. Re-run with --checks ci in lab 4.)"
fi
say "Done. Look at: https://github.com/$REPO/settings/rules and /settings/environments"
