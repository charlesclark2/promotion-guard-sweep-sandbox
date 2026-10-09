# /// script
# requires-python = ">=3.11"
# ///
"""Re-run promotion-guard on each pull request into `main` whose guard has not seen `main`'s tip.

GitHub has no "base branch moved" event and protect-main leaves "require branches to be up to date"
off, so a pull request into `main` keeps whatever `back-merge` verdict its last guard run gave. A
re-run replays the original event, and promotion-guard.yml's `back-merge` job fetches `main` and
`dev` live, so re-running a pull request's newest guard run is how its verdict catches up with a
hotfix (v1-e01-t12-promotion-guard-rerun). docs/process/branching-and-environments.md describes
the routes; this script is the one implementation behind all three of them, run by the
`rerun-promotion-guards` job in .github/workflows/back-merge.yml (v1-e01-t15-promotion-guard-sweep):

  push to main   the fast path: main just moved, so every guard run is behind it
  schedule       the backstop: it runs whether or not GitHub delivered any event
  dispatch       the manual route, for an operator who notices a lost push

What "already reflects" means. promotion-guard.yml's `back-merge` job posts a notice annotation
titled "promotion-guard evaluated main" whose message is the `main` commit it fetched and compared.
A pull request is current when the newest guard run for its head (its latest attempt) recorded the
commit `main` points at now. Anything else is re-run: a different commit, or no record at all (a
run that stopped before recording, or one made before the record existed). Nothing is judged from
timestamps. A pull request with no guard run for its head cannot be re-run, because there is no run
to replay and no API starts a `pull_request` run; it is reported, and protect-main already blocks it,
since its required checks never reported.

Only pull requests whose base is `main` are touched: the listing asks for base=main, and each
result is checked again here. A guard run still in progress may have fetched `main` before it moved,
and GitHub refuses to re-run a run in progress, so the sweep waits for it (up to 5 minutes) and
then judges it like any other.

Output. A sweep that re-runs nothing and finds nothing wrong prints exactly one line. Each re-run
prints one line, and anything a person must act on is a ::warning:: or ::error:: workflow command.
Only numbers and validated commit SHAs are printed, never a branch name, title or description.

Exit codes: 0 every pull request is current or was re-run; 1 at least one needs a person (its
re-run was refused, or its run never finished); 2 the sweep could not run (an API call failed).

Standard library only, so the runner's own python3 runs it. GitHub is reached through `gh api`,
authenticated by GH_TOKEN.

Usage:
  GH_TOKEN=... python3 scripts/rerun_promotion_guards.py --repo owner/name
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

GUARDED_BASE = "main"
GUARD_WORKFLOW = "promotion-guard.yml"
# The job of promotion-guard.yml that compares main with dev, and the title of the notice it posts
# naming the main commit it compared. promotion-guard.yml must keep both in step with these.
RECORDING_JOB = "back-merge"
RECORD_TITLE = "promotion-guard evaluated main"

POLL_SECONDS = 15
WAIT_LIMIT_SECONDS = 300

OK, NEEDS_A_PERSON, COULD_NOT_RUN = 0, 1, 2

COMMIT_SHA = re.compile(r"[0-9a-f]{40}")


class SweepError(RuntimeError):
    """GitHub could not be asked, so the sweep has no answer to give."""


class RerunRefused(RuntimeError):
    """GitHub refused to re-run a run."""


@dataclass(frozen=True)
class PullRequest:
    number: int
    base_ref: str
    head_sha: str
    head_ref: str
    # Empty when the repository the head branch lived in has been deleted.
    head_repo: str


@dataclass(frozen=True)
class GuardRun:
    id: int
    status: str
    created_at: str
    head_branch: str
    head_repo: str

    @property
    def finished(self) -> bool:
        return self.status == "completed"


class GitHub(Protocol):
    def main_tip(self) -> str: ...

    def open_pull_requests_into_main(self) -> list[PullRequest]: ...

    def guard_runs_for(self, head_sha: str) -> list[GuardRun]: ...

    def recorded_main(self, run_id: int) -> str | None: ...

    def rerun(self, run_id: int) -> None: ...


# --------------------------------------------------------------------------------------------
# The decisions, as pure functions
# --------------------------------------------------------------------------------------------


def pull_requests_into_main(pulls: Sequence[PullRequest]) -> list[PullRequest]:
    """Only pull requests whose base is `main`, whatever the listing returned."""
    return [pull for pull in pulls if pull.base_ref == GUARDED_BASE]


def newest_guard_run(pull: PullRequest, runs: Sequence[GuardRun]) -> GuardRun | None:
    """The newest guard run for this pull request's head, from its own branch and repository.

    Runs are asked for by head commit, and a fork's pull request can share a commit with `dev`, so
    the branch and repository must match too. Only one open pull request into `main` can have a
    given head branch and repository.
    """
    own = [run for run in runs if run.head_branch == pull.head_ref and run.head_repo == pull.head_repo]
    return max(own, key=lambda run: (run.created_at, run.id), default=None)


def already_reflects(recorded_main: str | None, main_tip: str) -> bool:
    """Did the guard run compare against the commit `main` points at now?

    A run that recorded nothing is not known to have seen anything, so it does not reflect `main`.
    """
    return recorded_main is not None and recorded_main == main_tip


def recorded_main_in(annotations: Sequence[dict[str, Any]]) -> str | None:
    """The main commit named by the guard's own notice among a check run's annotations.

    GitHub adds notices of its own to check runs (runner image migrations, for one), so the notice
    is found by its title, and its message must be a full commit SHA and nothing else.
    """
    for annotation in annotations:
        if annotation.get("annotation_level") != "notice" or annotation.get("title") != RECORD_TITLE:
            continue
        message = str(annotation.get("message") or "").strip()
        if COMMIT_SHA.fullmatch(message):
            return message
    return None


def recording_check_run_id(jobs: Sequence[dict[str, Any]]) -> int | None:
    """The check run of the job that records the main commit, among one attempt's jobs."""
    for job in jobs:
        if job.get("name") == RECORDING_JOB:
            return int(job["id"])
    return None


class Outcome(Enum):
    CURRENT = "current"
    RERUN = "re-run"
    ALREADY_RERUNNING = "already being re-run"
    NO_RUN = "no guard run"
    HEAD_REPO_GONE = "head repository deleted"
    STILL_RUNNING = "still running"
    RERUN_REFUSED = "re-run refused"


NEEDS_ACTION = {Outcome.STILL_RUNNING, Outcome.RERUN_REFUSED}


def short(sha: str) -> str:
    return sha[:12]


# --------------------------------------------------------------------------------------------
# The sweep
# --------------------------------------------------------------------------------------------


@dataclass
class Sweep:
    github: GitHub
    out: Callable[[str], None] = print
    sleep: Callable[[float], None] = time.sleep
    poll_seconds: int = POLL_SECONDS
    wait_limit_seconds: int = WAIT_LIMIT_SECONDS

    def run(self) -> int:
        try:
            main_tip = self.github.main_tip()
            pulls = pull_requests_into_main(self.github.open_pull_requests_into_main())
            if not pulls:
                self.out(f"No pull requests are open against {GUARDED_BASE}.")
                return OK
            outcomes = {pull.number: self.judge(pull, main_tip) for pull in pulls}
        except SweepError as exc:
            self.out(f"::error::The promotion-guard sweep could not run: {exc}")
            return COULD_NOT_RUN
        self.out(summary(outcomes, main_tip))
        return NEEDS_A_PERSON if NEEDS_ACTION & set(outcomes.values()) else OK

    def newest_run(self, pull: PullRequest) -> GuardRun | None:
        return newest_guard_run(pull, self.github.guard_runs_for(pull.head_sha))

    def judge(self, pull: PullRequest, main_tip: str) -> Outcome:
        if not pull.head_repo:
            return Outcome.HEAD_REPO_GONE
        run = self.newest_run(pull)
        waited = 0
        while run is not None and not run.finished and waited < self.wait_limit_seconds:
            self.out(f"#{pull.number}: promotion-guard run {run.id} is {run.status}; waiting for it to finish.")
            self.sleep(self.poll_seconds)
            waited += self.poll_seconds
            run = self.newest_run(pull)
        if run is None:
            self.out(
                f"::warning::#{pull.number}: no promotion-guard run exists for head {pull.head_sha}, so "
                "there is nothing to re-run. Its required checks never reported, so protect-main blocks "
                "it; push to it or edit its description to start one."
            )
            return Outcome.NO_RUN
        if not run.finished:
            self.out(
                f"::error::#{pull.number}: promotion-guard run {run.id} did not finish within "
                f"{self.wait_limit_seconds // 60} minutes. Re-run its checks by hand."
            )
            return Outcome.STILL_RUNNING
        recorded = self.github.recorded_main(run.id)
        if already_reflects(recorded, main_tip):
            return Outcome.CURRENT
        try:
            self.github.rerun(run.id)
        except RerunRefused as exc:
            # A sweep started by another trigger may have re-run it a moment ago.
            again = self.newest_run(pull)
            if again is not None and (again.id != run.id or not again.finished):
                self.out(f"#{pull.number}: promotion-guard run {again.id} is already being re-run.")
                return Outcome.ALREADY_RERUNNING
            self.out(
                f"::error::#{pull.number}: could not re-run promotion-guard run {run.id} ({exc}). "
                "Re-run its checks by hand."
            )
            return Outcome.RERUN_REFUSED
        seen = f"main at {short(recorded)}" if recorded else "no recorded main commit"
        self.out(
            f"#{pull.number}: re-running promotion-guard run {run.id} for head {pull.head_sha}; "
            f"it evaluated {seen}, and main is at {short(main_tip)}."
        )
        return Outcome.RERUN


def summary(outcomes: dict[int, Outcome], main_tip: str) -> str:
    """One line for the whole sweep. When nothing was re-run and nothing is wrong, it is the only one."""
    count = len(outcomes)
    noun = "pull request" if count == 1 else "pull requests"
    head = f"Swept {count} {noun} open against {GUARDED_BASE} at {short(main_tip)}"
    if all(outcome is Outcome.CURRENT for outcome in outcomes.values()):
        return f"{head}: every newest promotion-guard run already evaluated that commit, so nothing was re-run."
    parts = []
    for outcome in Outcome:
        numbers = [f"#{number}" for number, got in outcomes.items() if got is outcome]
        if numbers:
            parts.append(f"{outcome.value} {', '.join(numbers)}")
    return f"{head}: " + "; ".join(parts) + "."


# --------------------------------------------------------------------------------------------
# GitHub through the gh command line
# --------------------------------------------------------------------------------------------


class GhCli:
    """:class:`GitHub` through `gh api`, authenticated by GH_TOKEN."""

    def __init__(
        self, repository: str, runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run
    ):
        self.repository = repository
        self._run = runner

    def _api(self, *arguments: str) -> str:
        try:
            completed = self._run(["gh", "api", *arguments], capture_output=True, text=True, check=False)
        except OSError as exc:
            raise SweepError(f"could not run gh: {exc}") from exc
        if completed.returncode != 0:
            raise SweepError(f"gh api {' '.join(arguments)} failed: {completed.stderr.strip()}")
        return completed.stdout

    def _json(self, *arguments: str) -> Any:
        text = self._api(*arguments)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise SweepError(f"gh api {' '.join(arguments)} returned no JSON: {exc}") from exc

    def main_tip(self) -> str:
        sha = self._json(f"repos/{self.repository}/git/ref/heads/{GUARDED_BASE}")["object"]["sha"]
        if not COMMIT_SHA.fullmatch(sha):
            raise SweepError(f"{GUARDED_BASE} resolved to {sha!r}, not a commit SHA")
        return sha

    def open_pull_requests_into_main(self) -> list[PullRequest]:
        # --slurp gathers every page into one JSON array of pages.
        pages = self._json(
            "--paginate",
            "--slurp",
            f"repos/{self.repository}/pulls?state=open&base={GUARDED_BASE}&per_page=100",
        )
        return [
            PullRequest(
                number=int(pull["number"]),
                base_ref=pull["base"]["ref"],
                head_sha=pull["head"]["sha"],
                head_ref=pull["head"]["ref"],
                head_repo=(pull["head"].get("repo") or {}).get("full_name") or "",
            )
            for page in pages
            for pull in page
        ]

    def guard_runs_for(self, head_sha: str) -> list[GuardRun]:
        listing = self._json(
            f"repos/{self.repository}/actions/workflows/{GUARD_WORKFLOW}/runs"
            f"?event=pull_request&head_sha={head_sha}&per_page=100"
        )
        return [
            GuardRun(
                id=int(run["id"]),
                status=run["status"],
                created_at=run["created_at"],
                head_branch=run["head_branch"],
                head_repo=(run.get("head_repository") or {}).get("full_name") or "",
            )
            for run in listing["workflow_runs"]
        ]

    def recorded_main(self, run_id: int) -> str | None:
        jobs = self._json(f"repos/{self.repository}/actions/runs/{run_id}/jobs?filter=latest&per_page=100")
        check_run = recording_check_run_id(jobs["jobs"])
        if check_run is None:
            return None
        annotations = self._json(f"repos/{self.repository}/check-runs/{check_run}/annotations?per_page=100")
        return recorded_main_in(annotations)

    def rerun(self, run_id: int) -> None:
        try:
            self._api("-X", "POST", f"repos/{self.repository}/actions/runs/{run_id}/rerun")
        except SweepError as exc:
            raise RerunRefused(str(exc)) from exc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True, help="owner/name of the repository to sweep")
    args = ap.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
        print(f"::error::--repo must be owner/name, not {args.repo!r}", file=sys.stderr)
        return COULD_NOT_RUN
    return Sweep(GhCli(args.repo)).run()


if __name__ == "__main__":
    sys.exit(main())
