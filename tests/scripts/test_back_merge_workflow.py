"""The shape of the promotion-guard re-run in back-merge.yml (v1-e01-t12, v1-e01-t15 ac1, ac3, ac4).

The re-run only does anything after a merge into main, on a schedule or on a dispatch, so no task
pull request exercises it. These tests hold the parts whose loss would be silent: a trigger that
stops reaching the re-run, a second copy of the re-run, a write permission that spreads or reaches
pull-request code, a dispatch input that reaches a shell, and a record the sweep can no longer find.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import rerun_promotion_guards as sweep_script  # noqa: E402

SWEEP_SCRIPT = "scripts/rerun_promotion_guards.py"


def workflow(name: str) -> dict[Any, Any]:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def triggers(flow: dict[Any, Any]) -> dict[str, Any]:
    # YAML 1.1 reads the bare key `on` as the boolean True.
    return flow[True]


def back_merge() -> dict[Any, Any]:
    return workflow("back-merge.yml")


def rerun_job() -> dict[str, Any]:
    return back_merge()["jobs"]["rerun-promotion-guards"]


WRITE = "write"


# --------------------------------------------------------------------------------------------
# Triggers: the fast path, the backstop and the manual route all reach the same job
# --------------------------------------------------------------------------------------------


def test_back_merge_runs_on_push_to_main_a_schedule_and_a_dispatch_and_never_on_a_pull_request() -> None:
    on = triggers(back_merge())
    assert set(on) == {"push", "schedule", "workflow_dispatch"}
    assert on["push"] == {"branches": ["main"]}


def test_the_dispatch_takes_no_input() -> None:
    """Nothing typed into the dispatch form can reach a shell, because there is no form."""
    assert triggers(back_merge())["workflow_dispatch"] in (None, {})


def test_the_schedule_sweeps_every_fifteen_minutes_off_the_hour() -> None:
    [schedule] = triggers(back_merge())["schedule"]
    minutes, *rest = schedule["cron"].split()
    assert rest == ["*", "*", "*", "*"]
    sweeps = sorted(int(minute) for minute in minutes.split(","))
    assert len(sweeps) == 4
    assert 0 not in sweeps
    assert {b - a for a, b in zip(sweeps, sweeps[1:] + [sweeps[0] + 60], strict=True)} == {15}


def test_every_trigger_runs_the_rerun_job_and_only_push_opens_the_back_merge_pull_request() -> None:
    jobs = back_merge()["jobs"]
    assert "if" not in jobs["rerun-promotion-guards"]
    assert jobs["open-back-merge-pull-request"]["if"] == "github.event_name == 'push'"


def test_there_is_one_re_run_and_it_is_the_script() -> None:
    """Forbidden: duplicating the re-run. Exactly one step in any workflow re-runs guard runs, and
    it is the script; no workflow calls the rerun endpoint itself."""
    rerun_call = re.compile(r"runs/\S*/rerun|gh run rerun")
    callers = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        flow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for name, job in flow["jobs"].items():
            for step in job.get("steps", []):
                assert not rerun_call.search(step.get("run", "")), f"{path.name} {name} re-runs runs itself"
                if SWEEP_SCRIPT in step.get("run", ""):
                    callers.append((path.name, name))
    assert callers == [("back-merge.yml", "rerun-promotion-guards")]


# --------------------------------------------------------------------------------------------
# Permissions: the shape t12 established (ac4)
# --------------------------------------------------------------------------------------------


def test_back_merge_grants_nothing_at_the_top_and_actions_write_only_to_the_rerun_job() -> None:
    flow = back_merge()
    assert flow["permissions"] == {}
    granted = {name: job["permissions"] for name, job in flow["jobs"].items()}
    assert granted == {
        "open-back-merge-pull-request": {"contents": "read", "pull-requests": "write"},
        "rerun-promotion-guards": {
            "actions": "write",
            "checks": "read",
            "contents": "read",
            "pull-requests": "read",
        },
    }


def test_no_other_workflow_job_holds_actions_write_except_the_ones_that_dispatch() -> None:
    holders = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        flow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for name, job in flow["jobs"].items():
            if (job.get("permissions") or {}).get("actions") == WRITE:
                holders.append((path.name, name))
        assert (flow.get("permissions") or {}).get("actions") != WRITE, path.name
    # dev-prerelease dispatches validate-dev (v1-e01-t10); refresh-generated-files dispatches ci (v1-e01-t16).
    assert holders == [
        ("back-merge.yml", "rerun-promotion-guards"),
        ("dev-prerelease.yml", "publish"),
        ("refresh-generated-files.yml", "dispatch-ci"),
    ]


def test_promotion_guard_holds_no_write_permission() -> None:
    flow = workflow("promotion-guard.yml")
    assert set(triggers(flow)) == {"pull_request"}
    assert flow["permissions"] == {"contents": "read"}
    for job in flow["jobs"].values():
        assert job["permissions"] == {"contents": "read"}


def test_the_rerun_job_checks_out_only_the_script_from_its_own_commit_of_main_or_dev() -> None:
    steps = rerun_job()["steps"]
    [checkout] = [step for step in steps if step.get("uses", "").startswith("actions/checkout@")]
    assert checkout["with"] == {
        "persist-credentials": False,
        "sparse-checkout": SWEEP_SCRIPT,
        "sparse-checkout-cone-mode": False,
    }
    # No `ref`: the commit the workflow itself runs from. The gate before it refuses any ref but
    # main and dev, so a dispatch on a pull request's branch checks out nothing.
    gate = steps[0]
    assert steps.index(checkout) == 1
    assert gate["if"] == "github.ref != 'refs/heads/main' && github.ref != 'refs/heads/dev'"
    assert "exit 1" in gate["run"]


def test_no_expression_reaches_a_run_block_of_the_rerun_job() -> None:
    for step in rerun_job()["steps"]:
        assert "${{" not in step.get("run", ""), step.get("name")


def test_the_rerun_job_passes_the_repository_and_token_through_env() -> None:
    [sweep] = [step for step in rerun_job()["steps"] if SWEEP_SCRIPT in step.get("run", "")]
    assert sweep["run"] == f'python3 {SWEEP_SCRIPT} --repo "$REPO"'
    assert sweep["env"] == {"GH_TOKEN": "${{ github.token }}", "REPO": "${{ github.repository }}"}


def test_a_scheduled_sweep_never_cancels_a_pushs_back_merge_pull_request() -> None:
    """Concurrency is per job: a pending push run is never replaced by a schedule's."""
    flow = back_merge()
    assert "concurrency" not in flow
    assert flow["jobs"]["open-back-merge-pull-request"]["concurrency"] == {
        "group": "back-merge",
        "cancel-in-progress": False,
    }
    sweep_group = flow["jobs"]["rerun-promotion-guards"]["concurrency"]
    assert sweep_group["cancel-in-progress"] is False
    assert "github.event_name == 'push'" in sweep_group["group"]


# --------------------------------------------------------------------------------------------
# The record the sweep reads
# --------------------------------------------------------------------------------------------


def test_promotion_guards_back_merge_job_records_main_before_it_checks() -> None:
    job = workflow("promotion-guard.yml")["jobs"][sweep_script.RECORDING_JOB]
    names = [step.get("name") for step in job["steps"]]
    record = names.index("Record the main commit this run compares")
    assert names.index("Fetch main and dev") < record < names.index("main holds nothing that dev lacks")
    run = job["steps"][record]["run"]
    title = sweep_script.RECORD_TITLE
    assert run == f'echo "::notice title={title}::$(git rev-parse refs/remotes/origin/main)"'
    assert "if" not in job["steps"][record]
