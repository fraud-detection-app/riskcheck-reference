# riskcheck-practice

A tiny Python project for practising **trunk-based delivery and GitHub Actions**. The code is
small on purpose: `riskcheck/score.py` gives a transaction a risk score from 0 to 1 using four plain
rules (big amount, money leaving the system, account emptied, amount larger than the balance). The
code does not matter in this class. What matters is what happens around it: pull requests, checks,
environments, releases and rollback.

Nothing here touches AWS, and nothing is really deployed. The "deploy" in lab 5 only prints what a
real deploy would do, and the Terraform in `infra/` creates nothing in any cloud.

## The code in one minute

```python
from riskcheck import score_transaction

score, reasons = score_transaction(250_000, 300_000, 50_000, "TRANSFER")
# score = 0.5, reasons = ["large amount (>= 200,000)", "risky transaction type (TRANSFER)"]
```

```bash
python -m pip install -r requirements.txt
python -m pytest -q          # 8 tests, well under a second
```

## The branch model: trunk-based development (GitHub Flow)

One long-lived branch, `main`. It is always releasable.

```
feature/*  --pull request-->  main   --one pipeline run-->  dev -> sit -> pre-prod -> prod -> release v<VERSION>
```

- Nobody pushes to `main`. Every change arrives by **pull request** from a short-lived `feature/*`
  branch, and the required check `test / pytest` must be green.
- **Environments are stages of the pipeline, not branches.** dev, sit, pre-prod and prod are
  GitHub Environments; a merge to `main` starts one run that moves through them in order.
  pre-prod and prod wait for a reviewer.
- **Build once, promote by commit SHA.** The run builds one wheel, uploads it as
  `riskcheck-sha-<40 hex>`, and the four deploy jobs download that same file. The run prints its
  sha256 in every environment: one file, four environments.
- **Releases are SemVer tags.** `VERSION` holds `MAJOR.MINOR.PATCH`. After prod succeeds the run
  creates the tag `v<VERSION>` and a GitHub Release, if that tag does not exist yet. Bumping
  `VERSION` is part of the pull request.
- **Rollback = deploy an older SHA** (`rollback.yml`), under the same approvals.
  **Hotfix = fix forward**: a small pull request to `main`, through the normal pipeline.
- **Infrastructure has its own pipeline** (`infra.yml`, `paths: infra/**`) in the same repo. In
  13b it becomes its own repo.

## The labs

The workflow files are in `labs/`. When a lab adds one, you **copy it into `.github/workflows/`**
(in a feature branch, through a pull request) so you watch each piece arrive.

| Lab | What you do | Workflow file | You will see |
| --- | --- | --- | --- |
| 1 | Push the repo, run the setup script | none | the ruleset and four Environments in Settings |
| 2 | Start from a template | `python-app.yml` (GitHub's starter) | a check on your first pull request |
| 3 | A tour of the syntax | `hello.yml` | triggers, inputs, contexts, a matrix, outputs, a summary |
| 4 | A reusable workflow as CI, and a required check | `tests.yml` + `ci.yml` (**test / pytest**) | a red check that blocks the merge button |
| 5 | Deliver: one merge, four environments, a release | `deliver.yml` | dev, sit, pre-prod and prod from one build; release `v0.1.0` |
| 6 | A second change, then a rollback | `rollback.yml` (and `infra.yml` arrives) | release `v0.2.0`; prod back on the `v0.1.0` build |
| 7 | Infra vs app | `infra.yml` | a plan per environment on the pull request, an apply through the approvals |

## Setting the repo up (instructor)

1. Create the public repo and push `main` with these files (the first commit).
2. **Lab 1:** `scripts/setup_repo.sh <owner>/<repo> --checks none` creates the four Environments
   (each accepts only `main`; pre-prod and prod need a reviewer: the person running the script) and the
   ruleset `protect-main` (pull request required, no force-push, no deletion, squash or merge commit).
3. **Lab 4:** run it again with `--checks ci`, once `ci.yml` has reported the check `test / pytest` on
   a pull request. `--dry-run` prints every request without sending it.

### The required-check name

`ci.yml` has a job `test` that **calls** the reusable workflow `tests.yml`, whose job is called `pytest`.
For a job that calls a reusable workflow, GitHub reports the check as `<calling job> / <called job>`,
so the name to require is **`test / pytest`** (it is `CI_CHECK` at the top of `setup_repo.sh`). Rename
either job and update that line. A required check whose name nobody reports blocks every pull request,
so the ruleset asks for the check only after it has been seen (lab 4).

### Two rules about required checks and `paths`

- A **required** workflow must run on **every** pull request: `ci.yml` has no `paths:` filter. A
  skipped required check stays "Waiting for status to be reported" and the merge is blocked forever,
  including infra-only pull requests.
- A workflow that is **not** required may filter by path: `infra.yml` runs only for `infra/**`, and
  `deliver.yml` ignores `infra/**` and `*.md`.

Two more instructor tools are **not part of this repo** and are never pushed to students' repos. They live in
the course folder next to the deck, in `class_pack/live/`: `live_run.sh` rehearses labs 1-7 against a real repo
and records each lab's commands and real output, and `live_to_deck.py` turns those logs into the data the deck
builder quotes.

## What is in the folder

```
riskcheck/        the package (score.py)
tests/            test_score.py: the 8 score tests (what CI runs)
tests/workflows/  course checks on the workflow files, setup_repo.sh and infra/ (no GitHub, no cloud):
                  python -m pytest tests/workflows -o addopts=""
VERSION           the release number, MAJOR.MINOR.PATCH (the wheel and the release tag follow it)
infra/            a tiny Terraform stack (terraform_data only) and envs/<name>.tfvars for the four environments
labs/             the seven workflow files, copied into .github/workflows/ as the labs ask
scripts/          setup_repo.sh (instructor only)
pyproject.toml    package info and pytest settings (Python 3.11 or newer)
requirements.txt  pytest (and pyyaml for the course checks)
```
