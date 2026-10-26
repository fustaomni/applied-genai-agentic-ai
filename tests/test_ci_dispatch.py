# tests/test_ci_dispatch.py
"""ci:dispatch: the gate runs on a pull request's head when GitHub created no run there (A.5).

ci:state found ci.yml registered and active, Actions open and operational, and no run for any
push or pull_request in any generated repository. These proofs replace gh, the workflow reader
and the clock with scripts of their answers, so nothing here reaches GitHub; the first reads
the committed gate workflow itself.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

import pytest

import spine
from ci_dispatch import ENTRYPOINT, POLICY, DispatchRequest, _triggers, main

HEAD = "c" * 40
BRANCH = "feature/ci-state"
DISPATCHABLE = ("pull_request", "push", "workflow_dispatch")
CODE_SCANNING = {
    "name": "CodeQL",
    "path": "dynamic/github-code-scanning/codeql",
    "status": "completed",
    "conclusion": "success",
    "event": "dynamic",
}
CI_RUNNING = {
    "name": "CI",
    "path": ".github/workflows/ci.yml",
    "status": "in_progress",
    "conclusion": None,
    "event": "pull_request",
}
CI_DISPATCHED = {**CI_RUNNING, "status": "queued", "event": "workflow_dispatch"}


class FakeGh:
    """gh as ci_dispatch calls it: the PR, the head's runs before and after, the dispatch."""

    def __init__(
        self, before: Sequence[Mapping[str, object]], after: Sequence[Mapping[str, object]]
    ) -> None:
        self.calls: list[list[str]] = []
        self.before = before
        self.after = after

    def dispatches(self) -> list[list[str]]:
        return [call for call in self.calls if call[:2] == ["workflow", "run"]]

    def __call__(self, args: list[str]) -> tuple[int, str]:
        self.calls.append(list(args))
        if args[:2] == ["pr", "view"]:
            return 0, json.dumps({"number": 3, "headRefOid": HEAD, "headRefName": BRANCH})
        if args[0] == "api" and "/actions/runs?" in args[-1]:
            runs = self.after if self.dispatches() else self.before
            return 0, json.dumps({"total_count": len(runs), "workflow_runs": list(runs)})
        return 0, ""


def _run(gh: FakeGh, triggers: tuple[str, ...] | None = DISPATCHABLE) -> int:
    return main([], gh=gh, triggers=lambda: triggers, sleep=lambda _: None)


def _printed(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    printed: dict[str, object] = json.loads(capsys.readouterr().out)
    return printed


def test_the_gate_workflow_can_be_dispatched() -> None:
    """The committed gate declares workflow_dispatch, read exactly as ci:dispatch reads it."""
    triggers = _triggers()
    assert triggers is not None
    assert "workflow_dispatch" in triggers, triggers


def test_a_dropped_trigger_is_dispatched_and_its_run_seen(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No run of the gate on the head: it is dispatched, and done only once its run is seen."""
    gh = FakeGh([CODE_SCANNING], [CODE_SCANNING, CI_DISPATCHED])
    assert _run(gh) == 0
    printed = _printed(capsys)
    assert printed["code"] == "ci_dispatched", printed
    assert gh.dispatches() == [["workflow", "run", "ci.yml", "--ref", BRANCH]], gh.calls


def test_nothing_is_dispatched_while_a_run_exists(capsys: pytest.CaptureFixture[str]) -> None:
    """A run of the gate already on the head is the event working: nothing to dispatch."""
    gh = FakeGh([CODE_SCANNING, CI_RUNNING], [CODE_SCANNING, CI_RUNNING])
    assert _run(gh) == 2
    message = str(_printed(capsys)["message"])
    assert "ERR_CI_DISPATCH_RUN_EXISTS" in message, message
    assert gh.dispatches() == [], gh.calls


def test_a_dispatch_whose_run_never_appears_halts(capsys: pytest.CaptureFixture[str]) -> None:
    """gh accepting a dispatch is not the gate running: unseen on the head, it halts."""
    gh = FakeGh([CODE_SCANNING], [CODE_SCANNING])
    assert _run(gh) == 1
    printed = _printed(capsys)
    assert printed["code"] == "dispatch_unobserved", printed
    assert len(gh.dispatches()) == 1, gh.calls


def test_a_ref_without_the_dispatch_trigger_is_refused(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """GitHub refuses to dispatch a workflow without the trigger, so it is refused first."""
    gh = FakeGh([CODE_SCANNING], [CODE_SCANNING, CI_DISPATCHED])
    assert _run(gh, triggers=("pull_request", "push")) == 2
    message = str(_printed(capsys)["message"])
    assert "ERR_CI_DISPATCH_NOT_DISPATCHABLE" in message, message
    assert gh.dispatches() == [], gh.calls


def test_an_absent_request_is_refused_by_the_policy() -> None:
    """Sent under any other key, the request is absent, and absence never passes."""
    request = DispatchRequest(
        pr=3,
        head=HEAD,
        branch=BRANCH,
        workflow=".github/workflows/ci.yml",
        triggers=DISPATCHABLE,
        runs=(),
    )
    found = spine.evaluate(request, "not_ci_dispatch", POLICY, ENTRYPOINT)
    codes = [rule.code for rule in found.rules if rule.outcome == "fail"]
    assert "ERR_CI_DISPATCH_INPUT_MISSING" in codes, found
