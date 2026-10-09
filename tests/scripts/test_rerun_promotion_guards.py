"""Tests for `scripts/rerun_promotion_guards.py`, the one re-run behind the push, the schedule and
the dispatch in back-merge.yml (v1-e01-t15-promotion-guard-sweep).

All offline. The sweep runs against :class:`FakeGitHub`; :class:`GhCli` runs against a fake `gh`
whose JSON is shaped like the real API's (the field names and the annotation GitHub adds of its
own were read from a real promotion-guard run on 2026-10-08). Expected lines are written by hand.

The three decisions the task rests on each have tests that fail when that decision is broken:
"already reflects" (current, moved, no record), the base-branch filter, and a pull request with no
guard run at all.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import rerun_promotion_guards as sweep_script  # noqa: E402
from rerun_promotion_guards import GuardRun, PullRequest  # noqa: E402

REPO = "charlesclark2/debate-intelligence"
FORK = "someone/debate-intelligence"
MAIN_TIP = "1111111111111111111111111111111111111111"
OLD_MAIN = "2222222222222222222222222222222222222222"
DEV_HEAD = "dddddddddddddddddddddddddddddddddddddddd"
HOTFIX_HEAD = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
TASK_HEAD = "ffffffffffffffffffffffffffffffffffffffff"

PROMOTION = PullRequest(10, "main", DEV_HEAD, "dev", REPO)
HOTFIX = PullRequest(11, "main", HOTFIX_HEAD, "hotfix/fix-login", REPO)
TASK_INTO_DEV = PullRequest(12, "dev", TASK_HEAD, "task/v1-e04-t02-http-fetcher", REPO)
FORK_DEV = PullRequest(13, "main", DEV_HEAD, "dev", FORK)
GONE_FORK = PullRequest(14, "main", TASK_HEAD, "dev", "")


def run(run_id: int, created_at: str, pull: PullRequest, status: str = "completed") -> GuardRun:
    return GuardRun(run_id, status, created_at, pull.head_ref, pull.head_repo)


class FakeGitHub:
    """Answers from fixed data. `runs` maps a head commit to what each successive listing returns;
    the last listing repeats, so a run can be in progress for a few polls and then finish."""

    def __init__(
        self,
        pulls: Sequence[PullRequest],
        runs: dict[str, list[list[GuardRun]]],
        recorded: dict[int, str | None],
        main_tip: str = MAIN_TIP,
        refuse: frozenset[int] = frozenset(),
        listing_fails: bool = False,
    ) -> None:
        self.pulls = list(pulls)
        self.runs = runs
        self.recorded = recorded
        self.tip = main_tip
        self.refuse = refuse
        self.listing_fails = listing_fails
        self.listings: dict[str, int] = {}
        self.reruns: list[int] = []

    def main_tip(self) -> str:
        return self.tip

    def open_pull_requests_into_main(self) -> list[PullRequest]:
        if self.listing_fails:
            raise sweep_script.SweepError("gh api repos/x/pulls failed: HTTP 502")
        return self.pulls

    def guard_runs_for(self, head_sha: str) -> list[GuardRun]:
        listings = self.runs.get(head_sha, [[]])
        index = self.listings.get(head_sha, 0)
        self.listings[head_sha] = index + 1
        return listings[min(index, len(listings) - 1)]

    def recorded_main(self, run_id: int) -> str | None:
        return self.recorded.get(run_id)

    def rerun(self, run_id: int) -> None:
        if run_id in self.refuse:
            raise sweep_script.RerunRefused("HTTP 403: This workflow run cannot be rerun")
        self.reruns.append(run_id)


def sweep(github: FakeGitHub) -> tuple[int, list[str], list[float]]:
    lines: list[str] = []
    slept: list[float] = []
    code = sweep_script.Sweep(github, out=lines.append, sleep=slept.append).run()
    return code, lines, slept


# --------------------------------------------------------------------------------------------
# The quiet case and "already reflects"
# --------------------------------------------------------------------------------------------


def test_no_open_pull_request_into_main_prints_one_line() -> None:
    github = FakeGitHub([], {}, {})
    assert sweep(github) == (0, ["No pull requests are open against main."], [])
    assert github.reruns == []


def test_a_sweep_where_nothing_moved_re_runs_nothing_and_prints_one_line() -> None:
    github = FakeGitHub(
        [PROMOTION, HOTFIX],
        {
            DEV_HEAD: [[run(501, "2026-10-08T07:54:12Z", PROMOTION)]],
            HOTFIX_HEAD: [[run(601, "2026-10-08T08:00:00Z", HOTFIX)]],
        },
        {501: MAIN_TIP, 601: MAIN_TIP},
    )
    code, lines, _ = sweep(github)
    assert github.reruns == []
    assert code == 0
    assert lines == [
        "Swept 2 pull requests open against main at 111111111111: every newest promotion-guard run "
        "already evaluated that commit, so nothing was re-run."
    ]


def test_a_guard_run_that_evaluated_an_older_main_is_re_run() -> None:
    github = FakeGitHub(
        [PROMOTION], {DEV_HEAD: [[run(501, "2026-10-08T07:54:12Z", PROMOTION)]]}, {501: OLD_MAIN}
    )
    code, lines, _ = sweep(github)
    assert github.reruns == [501]
    assert code == 0
    assert lines == [
        f"#10: re-running promotion-guard run 501 for head {DEV_HEAD}; it evaluated main at "
        "222222222222, and main is at 111111111111.",
        "Swept 1 pull request open against main at 111111111111: re-run #10.",
    ]


def test_a_guard_run_that_recorded_no_main_commit_is_re_run() -> None:
    """No record is not evidence of having seen main: a run that stopped before recording, or one
    from before the record existed, is re-run rather than trusted."""
    github = FakeGitHub([PROMOTION], {DEV_HEAD: [[run(501, "2026-10-08T07:54:12Z", PROMOTION)]]}, {501: None})
    code, lines, _ = sweep(github)
    assert github.reruns == [501]
    assert code == 0
    assert lines[0] == (
        f"#10: re-running promotion-guard run 501 for head {DEV_HEAD}; it evaluated no recorded main "
        "commit, and main is at 111111111111."
    )


def test_only_the_newest_guard_run_counts() -> None:
    older_saw_main = FakeGitHub(
        [PROMOTION],
        {
            DEV_HEAD: [
                [run(501, "2026-10-08T07:54:12Z", PROMOTION), run(500, "2026-10-08T07:50:00Z", PROMOTION)]
            ]
        },
        {500: MAIN_TIP, 501: OLD_MAIN},
    )
    assert sweep(older_saw_main)[0] == 0
    assert older_saw_main.reruns == [501]

    newest_saw_main = FakeGitHub(
        [PROMOTION],
        {
            DEV_HEAD: [
                [run(500, "2026-10-08T07:50:00Z", PROMOTION), run(501, "2026-10-08T07:54:12Z", PROMOTION)]
            ]
        },
        {500: OLD_MAIN, 501: MAIN_TIP},
    )
    assert sweep(newest_saw_main)[0] == 0
    assert newest_saw_main.reruns == []


def test_already_reflects_is_equality_with_the_tip_and_never_true_without_a_record() -> None:
    assert sweep_script.already_reflects(MAIN_TIP, MAIN_TIP) is True
    assert sweep_script.already_reflects(OLD_MAIN, MAIN_TIP) is False
    assert sweep_script.already_reflects(None, MAIN_TIP) is False


# --------------------------------------------------------------------------------------------
# Only pull requests based on main
# --------------------------------------------------------------------------------------------


def test_a_pull_request_based_on_another_branch_is_never_touched_even_if_the_listing_returns_it() -> None:
    github = FakeGitHub(
        [PROMOTION, TASK_INTO_DEV],
        {
            DEV_HEAD: [[run(501, "2026-10-08T07:54:12Z", PROMOTION)]],
            TASK_HEAD: [[run(701, "2026-10-08T07:00:00Z", TASK_INTO_DEV)]],
        },
        {501: OLD_MAIN, 701: OLD_MAIN},
    )
    code, lines, _ = sweep(github)
    assert github.reruns == [501]
    assert TASK_HEAD not in github.listings
    assert code == 0
    assert lines[-1] == "Swept 1 pull request open against main at 111111111111: re-run #10."


def test_a_listing_of_only_other_bases_is_the_no_pull_request_case() -> None:
    github = FakeGitHub(
        [TASK_INTO_DEV], {TASK_HEAD: [[run(701, "2026-10-08T07:00:00Z", TASK_INTO_DEV)]]}, {701: OLD_MAIN}
    )
    assert sweep(github) == (0, ["No pull requests are open against main."], [])
    assert github.reruns == []


def test_a_fork_sharing_dev_head_commit_has_its_own_run_re_run_not_the_promotions() -> None:
    github = FakeGitHub(
        [FORK_DEV],
        {
            DEV_HEAD: [
                [run(501, "2026-10-08T07:54:12Z", PROMOTION), run(900, "2026-10-08T07:30:00Z", FORK_DEV)]
            ]
        },
        {501: OLD_MAIN, 900: OLD_MAIN},
    )
    assert sweep(github)[0] == 0
    assert github.reruns == [900]


# --------------------------------------------------------------------------------------------
# Pull requests the sweep cannot re-run
# --------------------------------------------------------------------------------------------


def test_a_pull_request_with_no_guard_run_at_all_is_reported_not_passed_over() -> None:
    github = FakeGitHub(
        [HOTFIX, PROMOTION], {DEV_HEAD: [[run(501, "2026-10-08T07:54:12Z", PROMOTION)]]}, {501: MAIN_TIP}
    )
    code, lines, _ = sweep(github)
    assert github.reruns == []
    assert code == 0
    assert lines == [
        f"::warning::#11: no promotion-guard run exists for head {HOTFIX_HEAD}, so there is nothing to "
        "re-run. Its required checks never reported, so protect-main blocks it; push to it or edit its "
        "description to start one.",
        "Swept 2 pull requests open against main at 111111111111: current #10; no guard run #11.",
    ]


def test_a_pull_request_whose_head_repository_is_gone_is_named_in_the_summary() -> None:
    github = FakeGitHub(
        [GONE_FORK], {TASK_HEAD: [[run(950, "2026-10-08T07:00:00Z", GONE_FORK)]]}, {950: OLD_MAIN}
    )
    code, lines, _ = sweep(github)
    assert github.reruns == []
    assert code == 0
    assert lines == ["Swept 1 pull request open against main at 111111111111: head repository deleted #14."]


# --------------------------------------------------------------------------------------------
# Runs in progress, refusals and failures
# --------------------------------------------------------------------------------------------


def test_a_run_in_progress_is_waited_for_and_then_judged_on_what_it_recorded() -> None:
    in_progress = run(501, "2026-10-08T07:54:12Z", PROMOTION, status="in_progress")
    finished = run(501, "2026-10-08T07:54:12Z", PROMOTION)
    saw_tip = FakeGitHub([PROMOTION], {DEV_HEAD: [[in_progress], [in_progress], [finished]]}, {501: MAIN_TIP})
    code, lines, slept = sweep(saw_tip)
    assert (code, saw_tip.reruns, slept) == (0, [], [15, 15])
    assert lines[:2] == ["#10: promotion-guard run 501 is in_progress; waiting for it to finish."] * 2

    saw_old = FakeGitHub([PROMOTION], {DEV_HEAD: [[in_progress], [finished]]}, {501: OLD_MAIN})
    assert sweep(saw_old)[0] == 0
    assert saw_old.reruns == [501]


def test_a_run_that_never_finishes_fails_the_sweep_after_five_minutes() -> None:
    in_progress = run(501, "2026-10-08T07:54:12Z", PROMOTION, status="queued")
    github = FakeGitHub([PROMOTION], {DEV_HEAD: [[in_progress]]}, {})
    code, lines, slept = sweep(github)
    assert code == 1
    assert slept == [15] * 20
    assert github.reruns == []
    assert lines[-2] == (
        "::error::#10: promotion-guard run 501 did not finish within 5 minutes. Re-run its checks by hand."
    )


def test_a_refused_re_run_fails_the_sweep_and_the_others_are_still_re_run() -> None:
    github = FakeGitHub(
        [PROMOTION, HOTFIX],
        {
            DEV_HEAD: [[run(501, "2026-10-08T07:54:12Z", PROMOTION)]],
            HOTFIX_HEAD: [[run(601, "2026-10-08T08:00:00Z", HOTFIX)]],
        },
        {501: OLD_MAIN, 601: OLD_MAIN},
        refuse=frozenset({501}),
    )
    code, lines, _ = sweep(github)
    assert code == 1
    assert github.reruns == [601]
    assert lines[0] == (
        "::error::#10: could not re-run promotion-guard run 501 (HTTP 403: This workflow run cannot be "
        "rerun). Re-run its checks by hand."
    )
    assert (
        lines[-1]
        == "Swept 2 pull requests open against main at 111111111111: re-run #11; re-run refused #10."
    )


def test_a_refusal_because_another_sweep_just_re_ran_it_is_not_a_failure() -> None:
    finished = run(501, "2026-10-08T07:54:12Z", PROMOTION)
    rerunning = run(501, "2026-10-08T07:54:12Z", PROMOTION, status="queued")
    github = FakeGitHub(
        [PROMOTION], {DEV_HEAD: [[finished], [rerunning]]}, {501: OLD_MAIN}, refuse=frozenset({501})
    )
    code, lines, _ = sweep(github)
    assert code == 0
    assert lines == [
        "#10: promotion-guard run 501 is already being re-run.",
        "Swept 1 pull request open against main at 111111111111: already being re-run #10.",
    ]


def test_an_api_failure_means_the_sweep_could_not_run() -> None:
    github = FakeGitHub([PROMOTION], {}, {}, listing_fails=True)
    assert sweep(github) == (
        2,
        ["::error::The promotion-guard sweep could not run: gh api repos/x/pulls failed: HTTP 502"],
        [],
    )


# --------------------------------------------------------------------------------------------
# Reading the record
# --------------------------------------------------------------------------------------------

# GitHub's own notice on a real back-merge check run, 2026-10-08, and the one promotion-guard.yml posts.
GITHUB_NOTICE = {
    "path": ".github",
    "start_line": 1,
    "annotation_level": "notice",
    "title": "",
    "message": '"The ubuntu-latest label will migrate to Ubuntu 26 beginning October 19, 2026. For more '
    'information, see https://github.com/actions/runner-images/issues/14748"',
    "raw_details": "",
}
GUARD_NOTICE = {
    "path": ".github",
    "start_line": 1,
    "annotation_level": "notice",
    "title": "promotion-guard evaluated main",
    "message": MAIN_TIP,
    "raw_details": "",
}


def test_the_record_is_the_guards_own_notice_and_not_githubs() -> None:
    assert sweep_script.recorded_main_in([GITHUB_NOTICE, GUARD_NOTICE]) == MAIN_TIP
    assert sweep_script.recorded_main_in([GITHUB_NOTICE]) is None
    assert sweep_script.recorded_main_in([]) is None


@pytest.mark.parametrize(
    "forged",
    [
        {**GUARD_NOTICE, "annotation_level": "warning"},
        {**GUARD_NOTICE, "title": "promotion-guard evaluated dev"},
        {**GUARD_NOTICE, "message": MAIN_TIP[:12]},
        {**GUARD_NOTICE, "message": f"{MAIN_TIP} and more"},
        {**GUARD_NOTICE, "message": DEV_HEAD.upper()},
    ],
)
def test_anything_but_a_bare_sha_under_the_exact_title_is_no_record(forged: dict[str, Any]) -> None:
    assert sweep_script.recorded_main_in([forged]) is None


def test_the_record_step_in_promotion_guard_produces_what_the_sweep_reads(tmp_path: Path) -> None:
    """Runs the record step's own command in a throwaway repository and parses its workflow command
    the way the runner turns `::notice title=T::M` into an annotation."""
    flow = yaml.safe_load((REPO_ROOT / ".github/workflows/promotion-guard.yml").read_text(encoding="utf-8"))
    job = flow["jobs"][sweep_script.RECORDING_JOB]
    assert job["name"] == sweep_script.RECORDING_JOB
    [record] = [step for step in job["steps"] if "::notice" in step.get("run", "")]

    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]
    env = {"PATH": os.environ["PATH"], "GIT_CONFIG_GLOBAL": "/dev/null", "HOME": str(tmp_path)}
    subprocess.run([*git, "init", "-q", str(tmp_path)], check=True, env=env)
    subprocess.run(
        [*git, "-C", str(tmp_path), "commit", "-q", "--allow-empty", "-m", "main"], check=True, env=env
    )
    sha = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"], check=True, env=env, capture_output=True, text=True
    ).stdout.strip()
    subprocess.run(
        ["git", "-C", str(tmp_path), "update-ref", "refs/remotes/origin/main", sha], check=True, env=env
    )

    out = subprocess.run(
        ["bash", "-c", record["run"]], cwd=tmp_path, check=True, env=env, capture_output=True, text=True
    ).stdout.strip()
    command, _, message = out.removeprefix("::").partition("::")
    level, _, properties = command.partition(" ")
    title = properties.removeprefix("title=")
    annotation = {"annotation_level": level, "title": title, "message": message}
    assert sweep_script.recorded_main_in([GITHUB_NOTICE, annotation]) == sha


# --------------------------------------------------------------------------------------------
# GhCli against API-shaped JSON
# --------------------------------------------------------------------------------------------


class FakeGh:
    """A `gh api` that answers by endpoint and remembers every call."""

    def __init__(self, answers: dict[str, Any], failing: frozenset[str] = frozenset()) -> None:
        self.answers = answers
        self.failing = failing
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        endpoint = next(a for a in args[2:] if a.startswith("repos/"))
        path = endpoint.split("?")[0]
        if path in self.failing:
            return subprocess.CompletedProcess(
                args, 1, "", "HTTP 403: Resource not accessible by integration"
            )
        return subprocess.CompletedProcess(args, 0, json.dumps(self.answers.get(path, {})), "")


def test_gh_cli_reads_the_tip_the_pull_requests_and_the_runs() -> None:
    gh = FakeGh(
        {
            f"repos/{REPO}/git/ref/heads/main": {
                "ref": "refs/heads/main",
                "object": {"sha": MAIN_TIP, "type": "commit"},
            },
            f"repos/{REPO}/pulls": [
                [
                    {
                        "number": 10,
                        "base": {"ref": "main"},
                        "head": {"sha": DEV_HEAD, "ref": "dev", "repo": {"full_name": REPO}},
                    },
                    {
                        "number": 14,
                        "base": {"ref": "main"},
                        "head": {"sha": TASK_HEAD, "ref": "dev", "repo": None},
                    },
                ],
                [
                    {
                        "number": 11,
                        "base": {"ref": "main"},
                        "head": {"sha": HOTFIX_HEAD, "ref": "hotfix/fix-login", "repo": {"full_name": REPO}},
                    }
                ],
            ],
            f"repos/{REPO}/actions/workflows/promotion-guard.yml/runs": {
                "total_count": 1,
                "workflow_runs": [
                    {
                        "id": 37746327641,
                        "status": "completed",
                        "conclusion": "success",
                        "created_at": "2026-10-08T07:54:12Z",
                        "head_branch": "dev",
                        "head_repository": {"full_name": REPO},
                    }
                ],
            },
        }
    )
    cli = sweep_script.GhCli(REPO, runner=gh)
    assert cli.main_tip() == MAIN_TIP
    assert cli.open_pull_requests_into_main() == [
        PullRequest(10, "main", DEV_HEAD, "dev", REPO),
        PullRequest(14, "main", TASK_HEAD, "dev", ""),
        PullRequest(11, "main", HOTFIX_HEAD, "hotfix/fix-login", REPO),
    ]
    assert cli.guard_runs_for(DEV_HEAD) == [
        GuardRun(37746327641, "completed", "2026-10-08T07:54:12Z", "dev", REPO)
    ]
    assert [
        "gh",
        "api",
        "--paginate",
        "--slurp",
        f"repos/{REPO}/pulls?state=open&base=main&per_page=100",
    ] in gh.calls
    assert [
        "gh",
        "api",
        f"repos/{REPO}/actions/workflows/promotion-guard.yml/runs?event=pull_request&head_sha={DEV_HEAD}&per_page=100",
    ] in gh.calls


def test_gh_cli_reads_the_record_from_the_latest_attempts_back_merge_check_run() -> None:
    gh = FakeGh(
        {
            f"repos/{REPO}/actions/runs/37746327641/jobs": {
                "total_count": 2,
                "jobs": [
                    {"id": 113208574281, "name": "promotion-source", "conclusion": "success"},
                    {"id": 113208574065, "name": "back-merge", "conclusion": "success"},
                ],
            },
            f"repos/{REPO}/check-runs/113208574065/annotations": [GITHUB_NOTICE, GUARD_NOTICE],
            f"repos/{REPO}/check-runs/113208574281/annotations": [{**GUARD_NOTICE, "message": OLD_MAIN}],
        }
    )
    assert sweep_script.GhCli(REPO, runner=gh).recorded_main(37746327641) == MAIN_TIP
    assert ["gh", "api", f"repos/{REPO}/actions/runs/37746327641/jobs?filter=latest&per_page=100"] in gh.calls


def test_gh_cli_finds_no_record_without_a_back_merge_job() -> None:
    gh = FakeGh({f"repos/{REPO}/actions/runs/7/jobs": {"total_count": 0, "jobs": []}})
    assert sweep_script.GhCli(REPO, runner=gh).recorded_main(7) is None


def test_gh_cli_turns_a_refused_re_run_into_rerun_refused_and_other_failures_into_sweep_errors() -> None:
    gh = FakeGh(
        {}, failing=frozenset({f"repos/{REPO}/actions/runs/501/rerun", f"repos/{REPO}/git/ref/heads/main"})
    )
    cli = sweep_script.GhCli(REPO, runner=gh)
    with pytest.raises(sweep_script.RerunRefused, match="HTTP 403"):
        cli.rerun(501)
    assert gh.calls[-1] == ["gh", "api", "-X", "POST", f"repos/{REPO}/actions/runs/501/rerun"]
    with pytest.raises(sweep_script.SweepError, match="HTTP 403"):
        cli.main_tip()


def test_main_refuses_a_repository_that_is_not_owner_slash_name(capsys: pytest.CaptureFixture[str]) -> None:
    assert sweep_script.main(["--repo", "owner/name; rm -rf /"]) == 2
    assert "--repo must be owner/name" in capsys.readouterr().err
