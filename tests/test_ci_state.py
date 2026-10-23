# tests/test_ci_state.py
"""ci:state: whether CI can run on a pull request's head, read as data (A.4).

On PR #1 and PR #2 the quality gate never registered while code scanning ran, and pr:logs,
which reads failed runs only, found nothing. These proofs replace gh and the status reader
with scripts of their answers, so nothing here reaches GitHub.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

import pytest

import spine
from ci_state import ENTRYPOINT, POLICY, CiStateRequest, WorkflowRun, main

HEAD = "b" * 40
OPEN = {"enabled": True, "allowed_actions": "all", "sha_pinning_required": False}
CI_RUNNING = {
    "name": "CI",
    "path": ".github/workflows/ci.yml",
    "status": "in_progress",
    "conclusion": None,
    "event": "pull_request",
}
CI_STARTUP_FAILED = {**CI_RUNNING, "status": "completed", "conclusion": "startup_failure"}
CODE_SCANNING = {
    "name": "CodeQL",
    "path": "dynamic/github-code-scanning/codeql",
    "status": "completed",
    "conclusion": "success",
    "event": "dynamic",
}
REGISTERED_CI = {"path": ".github/workflows/ci.yml", "state": "active"}


class FakeGh:
    """gh as ci_state calls it: the PR, the repository's Actions permissions, the head's runs."""

    def __init__(
        self,
        permissions: Mapping[str, object] | None,
        runs: Sequence[Mapping[str, object]],
        workflows: Sequence[Mapping[str, object]] = (REGISTERED_CI,),
    ) -> None:
        self.calls: list[list[str]] = []
        self.permissions = permissions
        self.runs = runs
        self.workflows = workflows

    def __call__(self, args: list[str]) -> tuple[int, str]:
        self.calls.append(list(args))
        if args[:2] == ["pr", "view"]:
            return 0, json.dumps({"number": 2, "headRefOid": HEAD})
        if args[0] == "api" and args[-1].endswith("/actions/permissions"):
            if self.permissions is None:
                return 1, ""
            return 0, json.dumps(self.permissions)
        if args[0] == "api" and args[-1].endswith("/actions/workflows"):
            body = {"total_count": len(self.workflows), "workflows": list(self.workflows)}
            return 0, json.dumps(body)
        if args[0] == "api" and "/actions/runs?" in args[-1]:
            return 0, json.dumps({"total_count": len(self.runs), "workflow_runs": self.runs})
        return 0, ""


def _run(gh: FakeGh, status: str | None = "operational") -> int:
    return main([], gh=gh, status=lambda: status)


def _printed(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    printed: dict[str, object] = json.loads(capsys.readouterr().out)
    return printed


def test_a_repository_workflow_run_on_the_head_proceeds(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A repository workflow running on the head is the one state in which CI can conclude."""
    assert _run(FakeGh(OPEN, [CODE_SCANNING, CI_RUNNING])) == 0
    printed = _printed(capsys)
    assert printed["code"] == "ci_runs_on_head", printed


def test_a_startup_failure_is_refused_naming_its_workflow(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Rejected before any job, a workflow posts no check run: only the run list shows it."""
    assert _run(FakeGh(OPEN, [CODE_SCANNING, CI_STARTUP_FAILED])) == 2
    message = str(_printed(capsys)["message"])
    assert "ERR_CI_STATE_STARTUP_FAILURE" in message, message
    assert ".github/workflows/ci.yml" in message, message


def test_actions_disabled_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(FakeGh({"enabled": False}, [])) == 2
    message = str(_printed(capsys)["message"])
    assert "ERR_CI_STATE_ACTIONS_DISABLED" in message, message


def test_restricted_actions_without_a_run_are_refused(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Under a selected-actions policy, a workflow using an unlisted action never starts."""
    assert _run(FakeGh({**OPEN, "allowed_actions": "selected"}, [CODE_SCANNING])) == 2
    message = str(_printed(capsys)["message"])
    assert "ERR_CI_STATE_ACTIONS_RESTRICTED" in message, message


def test_no_repository_workflow_run_is_refused_as_a_dropped_trigger(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Actions open and healthy, code scanning ran, yet no repository workflow ran here."""
    assert _run(FakeGh(OPEN, [CODE_SCANNING])) == 2
    message = str(_printed(capsys)["message"])
    assert "ERR_CI_STATE_NO_RUN" in message, message


def test_an_unread_permission_is_unobserved_never_assumed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A permissions read that failed is never taken as Actions enabled, even beside a run."""
    assert _run(FakeGh(None, [CI_RUNNING])) == 2
    message = str(_printed(capsys)["message"])
    assert "ERR_CI_STATE_UNOBSERVED" in message, message


def test_a_degraded_actions_service_is_named(capsys: pytest.CaptureFixture[str]) -> None:
    """No run while GitHub reports Actions degraded names the service, not the repository."""
    assert _run(FakeGh(OPEN, [CODE_SCANNING]), status="major_outage") == 2
    message = str(_printed(capsys)["message"])
    assert "ERR_CI_STATE_GITHUB_DEGRADED" in message, message
    assert "major_outage" in message, message


def test_an_absent_request_is_refused_by_the_policy() -> None:
    """Sent under any other key, the request is absent, and absence never passes."""
    request = CiStateRequest(
        pr=2,
        head=HEAD,
        actions_enabled=True,
        allowed_actions="all",
        sha_pinning_required=False,
        runs=(
            WorkflowRun(
                name="CI",
                path=".github/workflows/ci.yml",
                status="in_progress",
                conclusion=None,
                event="pull_request",
            ),
        ),
        actions_status="operational",
    )
    found = spine.evaluate(request, "not_ci_state", POLICY, ENTRYPOINT)
    codes = [rule.code for rule in found.rules if rule.outcome == "fail"]
    assert "ERR_CI_STATE_INPUT_MISSING" in codes, found


def test_an_unregistered_workflow_is_named(capsys: pytest.CaptureFixture[str]) -> None:
    """No registered workflow for the file: GitHub has nothing to dispatch on any event."""
    assert _run(FakeGh(OPEN, [CODE_SCANNING], workflows=[])) == 2
    message = str(_printed(capsys)["message"])
    assert "ERR_CI_STATE_WORKFLOW_UNREGISTERED" in message, message


def test_an_inactive_workflow_is_named(capsys: pytest.CaptureFixture[str]) -> None:
    """A registered workflow GitHub holds disabled creates no run, whatever its triggers."""
    disabled = {**REGISTERED_CI, "state": "disabled_manually"}
    assert _run(FakeGh(OPEN, [CODE_SCANNING], workflows=[disabled])) == 2
    message = str(_printed(capsys)["message"])
    assert "ERR_CI_STATE_WORKFLOW_INACTIVE" in message, message
    assert "disabled_manually" in message, message
