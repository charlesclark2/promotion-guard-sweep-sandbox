"""Every workflow job names a fixed runner image, never a moving `-latest` label (v1-e01-t15 ac8).

GitHub moves `ubuntu-latest` to Ubuntu 26 from 2026-10-19. A new image brings a new python3, a new
shellcheck and a new gh, and any of them could change what a promotion check decides. Pinning makes
that change a pull request someone reviews instead of a date in GitHub's calendar.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_FILES = sorted((REPO_ROOT / ".github" / "workflows").glob("*.y*ml"))
PINNED_RUNNERS = {"ubuntu-24.04"}


def strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from strings(key)
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def test_there_are_workflows_to_check() -> None:
    assert len(WORKFLOW_FILES) >= 6


@pytest.mark.parametrize("path", WORKFLOW_FILES, ids=lambda path: path.name)
def test_every_job_runs_on_a_pinned_image(path: Path) -> None:
    flow = yaml.safe_load(path.read_text(encoding="utf-8"))
    for name, job in flow["jobs"].items():
        if "uses" in job:
            continue  # a call to a reusable workflow names its runners there
        assert job.get("runs-on") in PINNED_RUNNERS, f"{path.name}: job {name} runs on {job.get('runs-on')!r}"


@pytest.mark.parametrize("path", WORKFLOW_FILES, ids=lambda path: path.name)
def test_no_value_anywhere_in_a_workflow_names_a_latest_runner(path: Path) -> None:
    """A matrix or an env value could carry the label into runs-on through an expression."""
    flow = yaml.safe_load(path.read_text(encoding="utf-8"))
    offenders = [value for value in strings(flow) if "-latest" in value]
    assert offenders == [], f"{path.name}: {offenders}"
