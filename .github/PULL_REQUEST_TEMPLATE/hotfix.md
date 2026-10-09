<!--
Hotfix: hotfix/<slug> into main, for an urgent production fix. A hotfix gets no exception to
"validated in dev": the hotfix head is deployed to dev by a manual workflow_dispatch and needs a
green validate-dev run and Charlie's approval before it merges, like any promotion.
https://github.com/charlesclark2/debate-intelligence/blob/dev/docs/process/branching-and-environments.md

The promotion-source check fails while the "Dev build:" line below is blank, and runs again
whenever this description is edited. Guidance sits in comments like this one, so a line holding
only its comment still counts as blank.

There is no line for the validate-dev run. protect-main requires the `validate-dev` commit status
on the hotfix head commit, and that status links its run. Dispatching dev-prerelease.yml on the
hotfix branch publishes the pre-release and then dispatches validate-dev for it.
-->

## Incident

Incident: <!-- link to the issue, or what broke, since when, and who is affected -->

## Fix

<!-- What this changes and why it is the smallest safe fix. -->

## Validation in dev

Dev build: <!-- id of the workflow_dispatch dev pre-release (V1) or dev deploy (V2+) of this hotfix head -->

The `validate-dev` status on the hotfix head commit is the validation: it names the pre-release it
installed and links the run. GitHub blocks the merge until it is green for the current head.

## Back-merge

When this merges, the back-merge workflow opens a "Back-merge main → dev" pull request. Merge it
into `dev` the same day with **Create a merge commit** (a squash leaves main's commits unreachable
from dev). Until it merges, the `back-merge` check fails on every promotion from dev. It does not
block another hotfix.

## Checklist

- [ ] `ci`, `promotion-source`, `back-merge` and `validate-dev` are green (`back-merge` passes for hotfix heads by design)
- [ ] The dev build above is the pre-release the `validate-dev` status names
- [ ] Charlie has approved this hotfix
- [ ] Merge with **Create a merge commit**, never squash or rebase
- [ ] The back-merge pull request is merged into `dev` with a merge commit the same day
- [ ] **The `rerun-promotion-guards` job in the back-merge workflow passed on the push this
      merge makes to `main`.** That is the fast path: it re-runs the promotion guards on every pull
      request still open against `main`, so a promotion opened before this hotfix turns its
      `back-merge` check red on its own instead of keeping a stale green. A scheduled sweep does the
      same every 15 minutes without needing any event, so a push GitHub never delivers is still
      caught; this item is for the minutes before that sweep. **If no "Back-merge main into dev" run
      appears for the merge commit**, GitHub lost the push: run that workflow from the Actions tab
      (Run workflow, from `dev`) rather than waiting, and open the back-merge pull request by hand,
      since only the push opens it. **If the job failed**, re-run the checks by hand on each
      promotion it names: re-run its promotion-guard run, or edit its description to retrigger.
      Until one of these happens, the promotion can merge a combination onto prod that dev never
      validated.
