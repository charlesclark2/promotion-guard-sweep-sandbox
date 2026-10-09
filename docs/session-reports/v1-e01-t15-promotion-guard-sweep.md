# Session report: v1-e01-t15-promotion-guard-sweep

| | |
|---|---|
| Task | `v1-e01-t15-promotion-guard-sweep` — Re-run the promotion guards without waiting for an event |
| Spec | [`plan_specs/v1/e01-repo-foundation/t15-promotion-guard-sweep.yaml`](../../plan_specs/v1/e01-repo-foundation/t15-promotion-guard-sweep.yaml) |
| Epic / release | `v1-e01-repo-foundation` / `v1.0` |
| Branch | `task/v1-e01-t15-promotion-guard-sweep` |
| Session status | PARTIAL: everything is built and tested; the sandbox proof (ac5) is the operator's. Goal stays `InProgress`; merge with `scripts/task pr --partial` |

## Summary

The promotion-guard re-run is now one script, `scripts/rerun_promotion_guards.py`. One job in
`back-merge.yml` runs it on three triggers: a push to `main` (the fast path, as in t12), a schedule
every 15 minutes (the backstop that needs no event), and a `workflow_dispatch` with no inputs (the
manual route). t12's inline shell is gone rather than copied.

The sweep is quiet when nothing has moved. promotion-guard's `back-merge` job now records the `main`
commit it compared, as a notice annotation on its own check run. The sweep re-runs a pull request
only when its newest guard run recorded a different commit or none. When nothing moved, it re-runs
nothing and prints one line.

`ci` gains a `workflow-lint` job. It runs actionlint 1.7.12, checksum-verified, with ShellCheck,
over every workflow. Every `runs-on` is pinned to `ubuntu-24.04`, and a test fails on any `-latest`
label.

Evidence so far:

* 28 offline tests of the sweep's decisions and 21 shape tests of the workflows.
* 12 mutants, each caught and restored byte for byte. They include the three the PM named: the
  "already reflects" comparison inverted, the base-branch filter removed, and the no-guard-run case
  skipped.
* A planted workflow with two findings failed the same script that `ci` runs, with exit 1.

**For the PM:** what's left is the sandbox proof (ac5): it needs Charlie's GitHub credentials and
waits for a scheduled slot. The procedure is under Operator follow-ups. Read Deviations 2 and 3
first. Deviation 2 covers "a pull request with no guard run is re-run", which can't be done as
written. Deviation 3 is a narrow transition case that touches the forbidden list.

## Plan nodes

| Node | Status | Notes |
|---|---|---|
| `sweep-triggers` — Schedule and dispatch, reusing t12's re-run | Done | `back-merge.yml` triggers, the `rerun-promotion-guards` job, `scripts/rerun_promotion_guards.py`, and the record step in `promotion-guard.yml` (280da70). Tests in 3628864. |
| `process-doc` — Say which routes are mechanical | Done, before the proof (Deviation 4) | `branching-and-environments.md` and the hotfix template (08a6ef1). |
| `lost-push-proof` — Prove it with the push suppressed | NOT RUN (operator) | Needs Charlie's credentials to create and drive a sandbox repository, plus a wait for a scheduled slot of up to about 30 minutes. The procedure, including how the push is suppressed, is under Operator follow-ups. |

## Acceptance criteria

| Criterion | Status | Evidence (command → result) |
|---|---|---|
| ac1 — a scheduled trigger re-runs promotion-guard for every open PR based on `main`, with no event; other bases untouched; the interval is justified in the workflow | PASS (offline); the live scheduled run is ac5 | `on.schedule` is `"7,22,37,52 * * * *"`, and the `rerun-promotion-guards` job has no event condition, so a scheduled run does exactly what a push does. The justification is in `back-merge.yml`'s header, "Why every 15 minutes". `test_back_merge_workflow.py` checks the triggers, the 15-minute spacing off the hour, and that every trigger reaches the job. `test_rerun_promotion_guards.py` checks the selection: PR #10 (`dev`) and #11 (`hotfix/*`) into `main` are both swept. #12 into `dev`, returned by the listing anyway, is never listed or re-run (`test_a_pull_request_based_on_another_branch_is_never_touched_even_if_the_listing_returns_it`). A fork sharing `dev`'s head commit has its own run re-run, not the promotion's. |
| ac2 — quiet when nothing to do; "already reflects" decided and stated | PASS (offline) | **The rule** (script docstring, the workflow header, the process doc): a PR is current when the newest guard run for its head, in its latest attempt, posted a notice titled `promotion-guard evaluated main` on its `back-merge` check run, and that notice names the commit `main` points at now. A different commit or no record means re-run. Nothing is judged from timestamps. **Quiet case:** `test_a_sweep_where_nothing_moved_re_runs_nothing_and_prints_one_line`: two current PRs → zero re-runs and exactly one line, `Swept 2 pull requests open against main at 111111111111: every newest promotion-guard run already evaluated that commit, so nothing was re-run.` With no PRs open, the one line is `No pull requests are open against main.` **The record is read the way GitHub stores it:** a real back-merge check run (2026-10-08) has `output.summary: null`, and GitHub's own notice about the runner migration sits among its annotations. `GhCli.recorded_main` against the real API returned `None` for that run, as it should, because the run predates the record. `test_the_record_step_in_promotion_guard_produces_what_the_sweep_reads` runs the record step's own command in a throwaway repository and parses its output. |
| ac3 — a manual `workflow_dispatch` runs the same sweep | PASS (offline); a live dispatch is step [C] of ac5 | `workflow_dispatch:` with no inputs (`test_the_dispatch_takes_no_input`). It reaches the same job (`test_every_trigger_runs_the_rerun_job_and_only_push_opens_the_back_merge_pull_request`). The job refuses any ref but `main` or `dev`, because it checks out the ref it runs from. |
| ac4 — the permission shape is unchanged; actionlint is clean across every workflow | PASS | `back-merge.yml` top level is `permissions: {}`. `actions: write` is held only by `rerun-promotion-guards`, beside `checks: read`, `contents: read` and `pull-requests: read`. The open job keeps `contents: read` and `pull-requests: write`. Across all workflows, the only `actions: write` holders are this job and t10's and t16's dispatchers (`test_no_other_workflow_job_holds_actions_write_except_the_ones_that_dispatch`). The write job checks out only `scripts/rerun_promotion_guards.py` (sparse, `persist-credentials: false`, no `ref`), after a gate that fails on any ref but `main`/`dev` (`test_the_rerun_job_checks_out_only_the_script_from_its_own_commit_of_main_or_dev`). promotion-guard.yml is still `contents: read` everywhere. `uv run --frozen scripts/actionlint.sh` → `actionlint 1.7.12 (darwin_arm64, checksum verified), with shellcheck 0.11.0 …`, no findings, exit 0, 1.1 s. |
| ac5 — proved against a real repository with the lost push simulated | **NOT RUN** | Operator follow-up 1, a sandbox repository. The push is suppressed by disabling `back-merge.yml` in the sandbox for the merge, so the file under test is byte-identical to this branch (Deviation 5). |
| ac6 — the process doc and the hotfix template name the backstop, the manual route and the fast path, and say what is mechanical and what is not | PASS | `branching-and-environments.md`: the section "When `main` moves…" now has a table of the three routes, a paragraph "Which pull requests it re-runs", and "What is mechanical now, and what is not". That list covers the minutes before the next sweep, the back-merge PR after a lost push (with the `gh pr create` to open it by hand), failed re-runs, PRs with no guard run, and the schedule's own limits. The hotfix template's last checklist item names the fast path and the backstop, and says what to do when no run appears. |
| ac7 — actionlint runs in `ci` over every workflow, pinned, and a known finding is shown failing first | PASS (locally); the first Linux run is this PR's own `ci` | `ci.yml` job `workflow-lint` runs `scripts/actionlint.sh`. It pins `VERSION=1.7.12` and the SHA-256 of each platform's archive, copied from the release's published `actionlint_1.7.12_checksums.txt` (downloaded archives: linux_amd64 `8aca8db9…`, darwin_arm64 `aba9ced2…`, both matching). The job is in `ci`'s needs and `PATH_FILTER_OF_JOB`, gated on a new `workflows` filter. **Planted finding:** a scratch `.github/workflows/planted-finding.yml` with `echo ${{ steps.frist.outputs.value }} $UNQUOTED` → `SC2086:info … Double quote to prevent globbing` and `property "frist" is not defined …`, **exit 1**. With the file removed → exit 0. **Checksum refusal:** a copy with one digit changed → `refusing to run it`, exit 2. |
| ac8 — every runner is pinned; a test fails on `-latest`; the report says what Ubuntu 26 needs (added on the PM's instruction, 2026-10-08) | PASS | All 20 `runs-on` lines in 6 workflows are now `ubuntu-24.04`. `tests/scripts/test_workflow_runners.py`: every job's `runs-on` is in `{"ubuntu-24.04"}`, and no string anywhere in a workflow contains `-latest`. Mutant "a runner back on ubuntu-latest" (validate-dev.yml) → both tests fail. Ubuntu 26 is under Follow-up work. |
| sweep-triggers: Workflows pass actionlint | PASS | `scripts/actionlint.sh .github/workflows/back-merge.yml .github/workflows/promotion-guard.yml` is covered by the run over every workflow above: exit 0. |
| lost-push-proof: The sweep turned a stale promotion red with no event | NOT RUN | ac5. |
| process-doc: Repository links still resolve | PASS | `uv run scripts/check_links.py` → `OK: 1281 relative links and anchors in 180 Markdown files` |

**Mutation runs**

Each mutant was applied to the committed file. The three test files then ran, and the file was
restored with `git checkout`, with its SHA-256 compared before and after; all 12 matched. The
script is `mutate.py` in the session scratchpad, and it was not committed. No Hypothesis property
is involved, so working agreement 8's database isolation does not apply.

| Mutant | File | Caught by (failed / total) |
|---|---|---|
| "already reflects" comparison inverted (`==` → `!=`) | rerun_promotion_guards.py | 10/54, including the quiet case and `test_a_guard_run_that_evaluated_an_older_main_is_re_run` |
| base-branch filter removed (`return list(pulls)`) | rerun_promotion_guards.py | 2/54: `…based_on_another_branch_is_never_touched…`, `…only_other_bases_is_the_no_pull_request_case` |
| no-record case skipped (no record treated as current) | rerun_promotion_guards.py | 2/54: `test_a_guard_run_that_recorded_no_main_commit_is_re_run`, `test_already_reflects_is_equality…` |
| no-guard-run case skipped silently | rerun_promotion_guards.py | 1/54: `test_a_pull_request_with_no_guard_run_at_all_is_reported_not_passed_over` |
| schedule trigger removed | back-merge.yml | 2/54 |
| dispatch input added | back-merge.yml | 1/54 |
| `actions: write` added to the open job | back-merge.yml | 2/54 |
| re-run job checks out the PR head | back-merge.yml | 1/54 |
| a second copy of the re-run (`gh api -X POST …/rerun`) | back-merge.yml | 2/54 |
| record step removed | promotion-guard.yml | 2/54 |
| record title drifts from the sweep's | promotion-guard.yml | 2/54 |
| a runner back on `ubuntu-latest` | validate-dev.yml | 2/54 |

Unmutated: `54 passed in 0.41s`. The wider run, `uv run --frozen pytest tests/docs tests/specs tests/scripts -q`, gave `833 passed in 43.79s`.
`uv run --frozen pytest tests/scripts/test_check_promotion_source.py -q` → `112 passed` (that file is
untouched). pre-commit on every changed file → all applicable hooks passed. `uv run --frozen python
scripts/check_command_blocks.py` → `OK: no # comments in 186 shell code blocks`. `uv run
scripts/validate_specs.py` → `OK: 310 files, 38 epics, 252 tasks, 20 releases`.

## Files changed

* `scripts/rerun_promotion_guards.py` (new): the one re-run. Standard library only, so the
  runner's `python3` runs it. It holds the pure decisions (`pull_requests_into_main`,
  `newest_guard_run`, `already_reflects`, `recorded_main_in`), the `Sweep` loop with t12's
  wait-for-in-progress, and `GhCli` over `gh api`.
* `.github/workflows/back-merge.yml`: `schedule` and `workflow_dispatch` triggers. The open job
  is limited to push, and its concurrency moved from the workflow to the job, so a sweep never
  replaces a pending push run. The re-run job's shell is replaced by a ref gate, a sparse checkout
  of the script, and one call to it, plus `checks: read` and `contents: read`. The header explains
  the three routes and the interval.
* `.github/workflows/promotion-guard.yml`: the `back-merge` job's record step (a notice with
  `main`'s SHA, between the fetch and the check), and comments. The guard's logic is unchanged.
* `.github/workflows/ci.yml`: the `workflow-lint` job, the `workflows` path filter, and
  `.github/workflows/**` added to the `python` filter, because tests now read the workflows. A
  header note on the runner pin.
* `scripts/actionlint.sh` (new): the pinned, checksum-verified actionlint, the same in `ci` and in a
  checkout.
* `.github/workflows/{dev-prerelease,refresh-generated-files,validate-dev}.yml`: `runs-on` only.
* `tests/scripts/test_rerun_promotion_guards.py`, `test_back_merge_workflow.py`,
  `test_workflow_runners.py` (new).
* `docs/process/branching-and-environments.md`, `.github/PULL_REQUEST_TEMPLATE/hotfix.md`: the
  routes, and what is and isn't mechanical.
* `plan_specs/v1/e01-repo-foundation/t15-promotion-guard-sweep.yaml`: ac8 and the packages, both
  marked "added on the PM's instruction, 2026-10-08". The phase is still `InProgress`.

## Deviations from the spec

1. **Packages beyond `.github/workflows` and `docs/process`**, on the PM's instruction:
   `scripts/rerun_promotion_guards.py`, `scripts/actionlint.sh`, `tests/scripts`, and the hotfix
   template, which the `process-doc` node already named. They are recorded in the spec's
   `constraints.packages` with the instruction's date.
2. **"A pull request with no guard run at all is re-run" can't be done as written, so it is
   reported instead.** A re-run replays an existing run. With no run for the current head, there
   is nothing to replay, and no API starts a `pull_request` run. Re-running an older head's run
   would post its checks on the old commit. Editing the PR to retrigger would need
   `pull-requests: write`, which the permission shape rules out. The sweep therefore treats the two
   cases this way:
   * **No record** (a run that stopped before recording, or a run from before the record existed):
     re-run, never trusted. Mutant 3 covers this.
   * **No run at all** (the PR's own `pull_request` event was lost): a `::warning::` naming the PR
     and the fix (push, or edit the description), and the summary line lists it. It is never
     passed over silently; mutant 4 covers this. It does not fail the job, because protect-main
     already blocks such a PR (its required checks never reported), and a red sweep every 15
     minutes would bury real failures.
3. **A narrow transition case touches the forbidden "re-runs guards on an unchanged repository
   every cycle".** A re-run replays the run's original workflow file. A guard run made before
   `promotion-guard.yml` had the record step can never record, so the sweep would re-run it every
   15 minutes until that PR gets a new run.
   * Promotions are not affected: this task merging into `dev` moves `dev`, which starts a new run
     on any open promotion from a file that records.
   * Hotfix PRs into `main` are affected: their merge ref takes `promotion-guard.yml` from `main`,
     which lacks the record step until this task is promoted. A hotfix PR open during that window
     loops until it merges, or until its description is edited once after the promotion lands.
   * Operator follow-up 3 says how to handle it.

   I chose this over a rule that would stop re-running a run that cannot record. Such a rule would
   need either a timestamp, which the PM ruled out, or "a sweep already re-ran this once", which
   would then miss a later move of `main`. Re-running a hotfix PR's guard can't change its result
   anyway, because a `hotfix/*` head passes `back-merge` without looking at `main`.
4. **`process-doc` was done before `lost-push-proof`**, against `dependsOn`, as in t12. The proof
   is the operator's, and the docs describe the mechanism as built. If the proof contradicts them,
   they will be corrected in the follow-up.
5. **How the push is suppressed in ac5: `back-merge.yml` is disabled in the sandbox for the merge.**
   It is not a direct ref update and not a removed trigger. protect-main forbids direct updates,
   and an update through the API is delivered as a push anyway. Removing the trigger would mean
   testing a file that differs from this branch. A disabled workflow receives no events, so the
   hotfix's push reaches nothing. It is re-enabled afterwards, and the next scheduled slot is the
   only thing that can act. The sandbox also deletes `ci.yml`, `dev-prerelease.yml`,
   `validate-dev.yml` and `refresh-generated-files.yml` from its copy, and requires only
   `promotion-source` and `back-merge` on its protect-main. That way "no job failed anywhere" is
   meaningful, and `BLOCKED` can only come from `back-merge`. This extends t12's Deviation 5 and
   leaves the real ruleset untouched.

## Decisions and assumptions

* **A script rather than a reusable workflow.** Both would give one implementation. The script
  wins on testing: the decisions the task rests on are pure functions with hand-written tests and
  real mutants, the pattern `check_promotion_source.py` and `validate_dev.py` already use. A
  reusable workflow would keep the logic as shell in YAML, which t12 could only test by extracting
  the block and running it under a fake `gh` in a scratchpad.

  The cost is that the write job now checks out a file, where t12 had no checkout. What makes that
  safe:
  * it is a sparse checkout of one file, from the workflow's own commit;
  * a gate step refuses any ref but `main` or `dev` before the checkout, so a dispatch on a PR's
    branch checks out nothing;
  * `persist-credentials: false`, and no expression reaches a `run:` block.

  Push runs check out `main` and the schedule checks out `dev`, both merged code.
* **Where the record lives.** Actions does not let a job write its own check run's
  `output.summary`; it was `null` on a real run. Step summaries are not readable through the API,
  and the run's display title is fixed before any step runs, so it can't hold a fetched SHA. A
  `::notice::` becomes a check-run annotation, which the sweep reads with `checks: read`. It
  records the commit the check actually compared: `git rev-parse refs/remotes/origin/main`, right
  after the fetch the check uses. GitHub adds notices of its own, so the sweep matches the exact
  title and requires a bare 40-character lowercase SHA.

  A PR's own code produces this notice, so a hostile PR could forge it and avoid re-runs. That is
  no new exposure: such a PR can already edit the guard itself (t08's known limit), and only `dev`
  and `hotfix/*` heads from this repository pass `promotion-source`.
* **Concurrency moved from the workflow to the jobs.** With a schedule in the same workflow, a
  workflow-level group would let a scheduled run replace a pending push run, cancelling the push's
  back-merge PR. Now:
  * the open job keeps `back-merge` and only ever runs on push;
  * the sweep's group is split into push and sweep, so a pending scheduled sweep replaced by a newer
    one loses nothing, because each reads the live state;
  * if a push sweep and a scheduled one overlap, a refused re-run whose run is now being re-run
    counts as handled, not as a failure (`test_a_refusal_because_another_sweep_just_re_ran_it_is_not_a_failure`).
* **The interval: 15 minutes, at minutes 7/22/37/52.** The reasoning is in the workflow header.
  Promotions are merged by hand, usually within an hour of opening, so four sweeps an hour bound a
  lost push's stale window at about 15 minutes plus start delay. One dropped slot makes that about
  30 minutes, and two still keep it inside the hour. A shorter interval would mostly add idle runs
  to the Actions list where a red run has to be seen. Minutes off the hour avoid GitHub's busiest
  scheduling time.
* **What the sweep prints.** Only PR numbers, run ids and validated SHAs; never branch names,
  titles or bodies. A PR whose head repository was deleted is named in the summary line instead of
  warned about every cycle; t12 warned about it. `promotion-source` fails such a PR anyway.
* **The `workflow-lint` job doesn't install the workspace.** It runs the script with the runner's
  `curl`, `tar` and preinstalled `shellcheck`, so it adds seconds to `ci`, not minutes.
* **Adding `.github/workflows/**` to the `python` filter.** The new tests read the workflows, and so
  did t16's existing `test_refresh_generated_files_workflow.py`. Without the filter, a PR touching
  only a workflow would skip the tests that hold its shape. A workflow-only PR now runs the Python
  jobs too; that keeps it inside the 5-minute budget the other PRs already meet.

## Operator follow-ups

### 1. The sandbox proof (ac5)

Expected runtime is about 45 minutes, most of it waiting for checks and for one scheduled slot.
The procedure creates a public sandbox repository under your account and pushes to it, and never
touches `charlesclark2/debate-intelligence` (it only reads protect-main from it). t12's sandbox no
longer exists, so this is a new one, `charlesclark2/promotion-guard-sweep-sandbox`.

Everything runs from the task worktree, plus a separate scratch worktree for the sandbox's
branches, so the task worktree's checkout never changes. Paste back the output at each bracketed
label, [A] to [N].

*Set up the sandbox.* This makes a sandbox-only commit that deletes the four workflows not under
test. `back-merge.yml` and `promotion-guard.yml` stay byte-identical to this branch. It pushes that
commit as both `main` and `dev`, makes `dev` the default branch (the schedule runs from it), and
copies protect-main with only `promotion-source` and `back-merge` required.

```bash
cd /Users/charlesclark/Documents/debate/debate-intelligence-tool/debate-intelligence-worktrees/v1-e01-t15-promotion-guard-sweep
SANDBOX=charlesclark2/promotion-guard-sweep-sandbox
SB="https://github.com/${SANDBOX}.git"
BODY='Dev build: sandbox'
git worktree add -b sandbox-base /tmp/t15-sweep-sandbox task/v1-e01-t15-promotion-guard-sweep
cd /tmp/t15-sweep-sandbox
git rm -q .github/workflows/ci.yml .github/workflows/dev-prerelease.yml .github/workflows/validate-dev.yml .github/workflows/refresh-generated-files.yml
git commit -q -m "Sandbox: only the promotion guards and back-merge run"
BASE=$(git rev-parse HEAD)
gh repo create "$SANDBOX" --public --description "Throwaway for the v1-e01-t15 sandbox proof; delete afterwards"
git push "$SB" "${BASE}:refs/heads/main" "${BASE}:refs/heads/dev"
gh repo edit "$SANDBOX" --default-branch dev --delete-branch-on-merge
gh api -X PUT "repos/${SANDBOX}/actions/permissions/workflow" -f default_workflow_permissions=read -F can_approve_pull_request_reviews=true
gh api repos/charlesclark2/debate-intelligence/rulesets/23638829 | jq '{name, target, enforcement, conditions, bypass_actors, rules: [.rules[] | if .type == "required_status_checks" then .parameters.required_status_checks |= map(select(.context == "promotion-source" or .context == "back-merge")) else . end]}' | gh api -X POST "repos/${SANDBOX}/rulesets" --input - --jq '[.name, (.rules[] | select(.type == "required_status_checks") | .parameters.required_status_checks[].context)]'
```

The last command prints `["protect-main","promotion-source","back-merge"]`.

*Open a promotion and confirm its guard recorded `main`'s tip.*

```bash
git switch -q -c sandbox-dev-change "$BASE"
echo dev > SANDBOX_DEV_CHANGE.txt && git add SANDBOX_DEV_CHANGE.txt && git commit -q -m "Sandbox dev change"
git push "$SB" HEAD:refs/heads/dev
PROMO=$(gh pr create --repo "$SANDBOX" --base main --head dev --title "Sandbox promotion" --body "$BODY"); PROMO=${PROMO##*/}
sleep 20; gh pr checks --repo "$SANDBOX" "$PROMO" --watch
RUN=$(gh run list --repo "$SANDBOX" --workflow promotion-guard.yml --branch dev --event pull_request --limit 1 --json databaseId --jq '.[0].databaseId')
JOB=$(gh api "repos/${SANDBOX}/actions/runs/${RUN}/jobs?filter=latest" --jq '.jobs[] | select(.name == "back-merge") | .id')
gh api "repos/${SANDBOX}/check-runs/${JOB}/annotations" --jq '.[] | select(.title == "promotion-guard evaluated main") | .message'
gh api "repos/${SANDBOX}/git/ref/heads/main" --jq .object.sha
```

* **[A]**: `promotion-source` and `back-merge` pass.
* **[B]**: the last two lines print the same SHA. The guard recorded the `main` it compared.

*The quiet case, through the dispatch (ac2, ac3).*

```bash
gh workflow run back-merge.yml --repo "$SANDBOX" --ref dev
sleep 20; QUIET=$(gh run list --repo "$SANDBOX" --workflow back-merge.yml --event workflow_dispatch --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch --repo "$SANDBOX" "$QUIET" --exit-status
gh run view --repo "$SANDBOX" "$QUIET" --log | grep -E 'Swept|re-running|No pull requests|::(warning|error)::'
gh api "repos/${SANDBOX}/actions/runs/${RUN}" --jq .run_attempt
```

* **[C]**: exactly one line, `Swept 1 pull request open against main at <sha>: every newest
  promotion-guard run already evaluated that commit, so nothing was re-run.`
* The run attempt is `1`, so nothing was re-run.

*Merge a hotfix with the push suppressed.* Disabling `back-merge.yml` means GitHub delivers the
merge's push to nothing. This is the lost push, made on purpose.

```bash
git switch -q -c hotfix/sandbox-lost-push "$BASE"
echo fix > SANDBOX_HOTFIX.txt && git add SANDBOX_HOTFIX.txt && git commit -q -m "Sandbox hotfix whose push is suppressed"
git push "$SB" hotfix/sandbox-lost-push
gh pr create --repo "$SANDBOX" --base main --head hotfix/sandbox-lost-push --title "Sandbox hotfix, push suppressed" --body "$BODY"
sleep 20; gh pr checks --repo "$SANDBOX" hotfix/sandbox-lost-push --watch
gh workflow disable back-merge.yml --repo "$SANDBOX"
gh pr merge --repo "$SANDBOX" hotfix/sandbox-lost-push --merge
MAIN=$(gh api "repos/${SANDBOX}/git/ref/heads/main" --jq .object.sha); echo "$MAIN"
sleep 60
gh run list --repo "$SANDBOX" --commit "$MAIN" --json workflowName,event,conclusion
gh run list --repo "$SANDBOX" --limit 50 --json workflowName,event,conclusion --jq '[.[] | select(.conclusion == "failure")]'
gh pr checks --repo "$SANDBOX" "$PROMO"
gh pr view --repo "$SANDBOX" "$PROMO" --json mergeStateStatus
gh api "repos/${SANDBOX}/compare/dev...main" --jq '[.commits[] | select(.parents | length == 1) | .commit.message]'
```

* **[D]**: the hotfix's two checks pass (`back-merge` passes for hotfix heads by design).
* **[E]**: `[]`. No workflow of any kind ran for the merge commit.
* **[F]**: `[]`. No run failed anywhere.
* **[G]**: `back-merge` still pass on the promotion. This is the stale green.
* **[H]**: `CLEAN`. The promotion could merge.
* **[I]**: `["Sandbox hotfix whose push is suppressed"]`. `main` holds a commit `dev` lacks.

*Let the schedule act.* Re-enable the workflow and wait for the next scheduled slot, without
touching the promotion. The loop polls every minute and usually ends within 15–30 minutes.

```bash
SINCE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
gh workflow enable back-merge.yml --repo "$SANDBOX"
until [ -n "$(gh run list --repo "$SANDBOX" --workflow back-merge.yml --event schedule --created ">=${SINCE}" --json databaseId --jq '.[0].databaseId // empty')" ]; do sleep 60; done
SWEEP=$(gh run list --repo "$SANDBOX" --workflow back-merge.yml --event schedule --created ">=${SINCE}" --json databaseId --jq '.[0].databaseId')
gh run watch --repo "$SANDBOX" "$SWEEP" --exit-status
gh run view --repo "$SANDBOX" "$SWEEP" --log | grep -E 'Swept|re-running|::(warning|error)::'
sleep 30; gh pr checks --repo "$SANDBOX" "$PROMO" --watch
gh pr view --repo "$SANDBOX" "$PROMO" --json mergeStateStatus
gh api "repos/${SANDBOX}/actions/runs/${RUN}" --jq '[.run_attempt, .triggering_actor.login]'
```

* **[J]**: the scheduled run succeeds and logs two lines: `#<PROMO>: re-running promotion-guard
  run <RUN> for head <sha>; it evaluated main at <old>, and main is at <new>.` and `Swept 1 pull
  request open against main at <new>: re-run #<PROMO>.`
* **[K]**: `back-merge` fails, with ``FAILED: `main` has 1 non-merge commit(s) that `dev` lacks``
  naming the sandbox hotfix.
* **[L]**: `BLOCKED`.
* **[M]**: `[2,"github-actions[bot]"]`. The sweep re-ran it, and nobody touched the promotion.

*Quiet again after the move.* The re-run recorded the new `main`, so a second sweep leaves it alone.

```bash
gh workflow run back-merge.yml --repo "$SANDBOX" --ref dev
sleep 20; AGAIN=$(gh run list --repo "$SANDBOX" --workflow back-merge.yml --event workflow_dispatch --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch --repo "$SANDBOX" "$AGAIN" --exit-status
gh run view --repo "$SANDBOX" "$AGAIN" --log | grep -E 'Swept|re-running|::(warning|error)::'
gh api "repos/${SANDBOX}/actions/runs/${RUN}" --jq .run_attempt
```

* **[N]**: one `Swept 1 pull request … nothing was re-run.` line, and the attempt is still `2`.

If [E] lists a `Back-merge main into dev` run, the disable didn't take effect before the merge, so
the push wasn't suppressed. Paste it and stop. If [J] shows a 403 on the re-run, paste the log.

*Clean up* once the results are pasted back:

```bash
cd /Users/charlesclark/Documents/debate/debate-intelligence-tool/debate-intelligence-worktrees/v1-e01-t15-promotion-guard-sweep
git worktree remove --force /tmp/t15-sweep-sandbox
git branch -D sandbox-base sandbox-dev-change hotfix/sandbox-lost-push
gh auth refresh -h github.com -s delete_repo
gh repo delete charlesclark2/promotion-guard-sweep-sandbox --yes
```

When [A]–[N] hold, ac5 and the `lost-push-proof` node pass. The Goal can then be set to
`Succeeded` in a follow-up spec PR, as in t08.

### 2. Look at this PR's own `ci` run

The `workflow-lint` job runs on Linux for the first time here. Its log should begin `actionlint
1.7.12 (linux_amd64, checksum verified), with shellcheck … from /usr/bin/shellcheck`, then pass. If
it says `without shellcheck`, the runner image dropped it. That is worth knowing before Ubuntu 26.

### 3. Between this merging into `dev` and its promotion

The schedule runs from `dev` as soon as this merges, while `main`'s push job is still t12's until
the promotion. Both are safe together.

If a `hotfix/*` pull request into `main` is open in that window, its guard runs can't record, for
the reason in Deviation 3. The sweep will then re-run them every 15 minutes. After the promotion
lands, edit that pull request's description once, which starts a run that records. Promotions need
nothing.

On the real repository, the first scheduled runs of *Back-merge main into dev* should each log one
line: `No pull requests are open against main.`, or a `Swept … nothing was re-run.` line.

## Follow-up work

* **Moving the runners to Ubuntu 26** (an E01 task when wanted). It needs all of these:
  * Change the 20 `runs-on` lines and `PINNED_RUNNERS` in `tests/scripts/test_workflow_runners.py`.
  * **Upgrade actionlint first:** 1.7.12 rejects `ubuntu-26.04` as an unknown label (checked:
    `label "ubuntu-26.04" is unknown`, exit 1). Take a release that knows it, with its version and
    all four checksums from its checksums file.
  * Run the standard-library scripts the guards and gates call with the runner's own `python3`
    (`check_promotion_source.py`, `rerun_promotion_guards.py`, `validate_dev.py`) on the new
    image's Python. They need 3.11 or newer, and their tests should run under it.
  * Check that the new image still ships `shellcheck` (its newer version may report findings that
    are new to the existing `run:` blocks), plus `gh` with `api --slurp`, `jq` and `git`.
  * Jobs that install Python through uv from `.python-version` are unaffected by the image's Python.
  * Run the promotion guards once on the new image in a sandbox before a real promotion depends on
    them. The required check names don't change, so a broken image would show as a red required
    check, not a silent pass.
* **The dispatch could also open the back-merge pull request.** After a lost push, the sweep turns
  the promotion red, but the back-merge pull request that the red check says to merge was never
  opened. The process doc gives the `gh pr create` to open it by hand. Letting the dispatch run
  `open-back-merge-pull-request` too (it is idempotent) would make recovery one click. It is out of
  this task's scope, because the spec says the dispatch performs "the same sweep".
* **The schedule stops after 60 idle days.** GitHub disables scheduled workflows in a public
  repository after 60 days without activity. It is documented in the process doc; nothing
  watches for it.

## PM review

<!-- Completed by the PM only. scripts/task pr refuses to open a PR unless the last Verdict in
this report is ACCEPTED. A later review is appended after this one; this one is never edited. -->

**Verdict:** PENDING
<!-- ACCEPTED / CHANGES_REQUESTED -->

**Reviewed by / date:**

**Notes:**
