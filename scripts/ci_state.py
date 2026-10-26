# scripts/ci_state.py
"""ci:state -- whether CI can run on a pull request's head, judged from what GitHub holds (A.4).

THE GATE THAT NEVER REGISTERED. On PR #1 and PR #2 the quality gate posted nothing through
two 20-minute pr windows while code scanning ran, and pr:logs, which reads failed runs only,
found nothing. A workflow rejected at startup creates no job and so no check run: only the
head's run list shows it, and only the repository's Actions permissions show a policy that
stops it.

EVIDENCE, THEN VERDICT. This reads the permissions, every run on the head in every state, and
GitHub's Actions status; runs.ci_state names the cause class. Nothing is changed.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from pydantic import Field, ValidationError

from bounded import Exited, run
from ci_rerun import actions_status
from command_outcome import announce
from contract_base import Contract, Reading
from spine import decide, enforce, evaluate, halted, reasons, refusal_code

ROOT = Path(__file__).resolve().parent.parent
COMMAND = "ci:state"
SUBJECT = "ci_state"
POLICY = ROOT / "policies" / "runs" / "ci_state"
ENTRYPOINT = "data.runs.ci_state.deny"
GH_DEADLINE = 60.0

Gh = Callable[[list[str]], tuple[int, str]]


class WorkflowRun(Contract):
    """One workflow run on the head, as GitHub lists it: in any status, with any conclusion."""

    name: str
    path: str
    status: str
    conclusion: str | None
    event: str


class RegisteredWorkflow(Contract):
    """A workflow GitHub holds registered for the repository, with the state it dispatches on."""

    path: str
    state: str


class CiStateRequest(Contract):
    """What ci:state observed: the PR, its head, the Actions policy, the runs, the service."""

    pr: int | None
    head: str | None
    actions_enabled: bool | None
    allowed_actions: str | None
    sha_pinning_required: bool | None
    runs: tuple[WorkflowRun, ...] | None
    actions_status: str | None
    workflows: tuple[RegisteredWorkflow, ...] | None = None


class _Pull(Reading):
    number: int
    head_ref_oid: str = Field(alias="headRefOid")


class _Permissions(Reading):
    enabled: bool
    allowed_actions: str | None = None
    sha_pinning_required: bool = False


class _Listed(Reading):
    name: str
    path: str
    status: str
    conclusion: str | None = None
    event: str


class _Runs(Reading):
    workflow_runs: tuple[_Listed, ...] = ()


class _Registered(Reading):
    path: str
    state: str


class _Workflows(Reading):
    workflows: tuple[_Registered, ...] = ()


def _gh(args: list[str]) -> tuple[int, str]:
    result = run(["gh", *args], deadline=GH_DEADLINE, cwd=ROOT)
    ended = result.termination
    return (ended.code if isinstance(ended, Exited) else -1), result.stdout


def _pull(gh: Gh) -> _Pull | None:
    code, out = gh(["pr", "view", "--json", "number,headRefOid"])
    try:
        return _Pull.model_validate_json(out) if code == 0 else None
    except ValidationError:
        return None


def _permissions(gh: Gh) -> _Permissions | None:
    code, out = gh(["api", "repos/{owner}/{repo}/actions/permissions"])
    try:
        return _Permissions.model_validate_json(out) if code == 0 else None
    except ValidationError:
        return None


def runs_on_head(gh: Gh, head: str) -> tuple[WorkflowRun, ...] | None:
    # EVERY STATUS, EVERY CONCLUSION: a startup_failure is a run, and a failure filter misses it.
    url = f"repos/{{owner}}/{{repo}}/actions/runs?head_sha={head}&per_page=100"
    code, out = gh(["api", url])
    if code != 0:
        return None
    try:
        listed = _Runs.model_validate_json(out).workflow_runs
    except ValidationError:
        return None
    return tuple(
        WorkflowRun(
            name=entry.name,
            path=entry.path,
            status=entry.status,
            conclusion=entry.conclusion,
            event=entry.event,
        )
        for entry in listed
    )


def _workflows(gh: Gh) -> tuple[RegisteredWorkflow, ...] | None:
    # THE REGISTRY GITHUB DISPATCHES FROM: a file it holds no active entry for never runs.
    code, out = gh(["api", "repos/{owner}/{repo}/actions/workflows"])
    if code != 0:
        return None
    try:
        listed = _Workflows.model_validate_json(out).workflows
    except ValidationError:
        return None
    return tuple(RegisteredWorkflow(path=entry.path, state=entry.state) for entry in listed)


def main(
    argv: Sequence[str] | None = None,
    *,
    gh: Gh = _gh,
    status: Callable[[], str | None] = actions_status,
) -> int:
    """ci:state -- judge whether CI can run on this branch's pull request head."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        usage = "usage: mise run run ci:state"
        stopped = halted(SUBJECT, ENTRYPOINT, POLICY, usage)
        return enforce(announce(COMMAND, stopped, "usage", usage, {}))
    pull = _pull(gh)
    head = None if pull is None else pull.head_ref_oid
    permissions = _permissions(gh)
    request = CiStateRequest(
        pr=None if pull is None else pull.number,
        head=head,
        actions_enabled=None if permissions is None else permissions.enabled,
        allowed_actions=None if permissions is None else permissions.allowed_actions,
        sha_pinning_required=None if permissions is None else permissions.sha_pinning_required,
        runs=None if head is None else runs_on_head(gh, head),
        actions_status=status(),
        workflows=_workflows(gh),
    )
    observed = request.model_dump(mode="json")
    found = evaluate(request, SUBJECT, POLICY, ENTRYPOINT)
    decision = decide(found)
    if decision.action != "proceed":
        code = refusal_code(decision, "ci_state_refused")
        return enforce(announce(COMMAND, decision, code, reasons(found), observed))
    message = f"a repository workflow runs on {str(head)[:12]}"
    return enforce(announce(COMMAND, decision, "ci_runs_on_head", message, observed))


if __name__ == "__main__":
    raise SystemExit(main())
