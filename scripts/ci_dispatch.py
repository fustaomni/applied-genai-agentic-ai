# scripts/ci_dispatch.py
"""ci:dispatch -- run the gate on a pull request's head when GitHub created no run there (A.5).

THE EVENT THAT NEVER BECAME A RUN. ci:state read ci.yml registered and active, Actions open
and operational, and no run for any push or pull_request in any generated repository, while
the source repository's ran as normal. A workflow_dispatch on the head branch runs that
branch's own gate, and the check it posts is the one the ruleset requires.

DECIDE, THEN ACT, THEN OBSERVE, as pr:checks does (D.217). runs.ci_dispatch allows it only
for a dispatchable gate with no run on the head; success is the gate's run seen on the head,
never gh accepting the dispatch.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

import yaml
from pydantic import Field, JsonValue, ValidationError, model_validator

from bounded import Exited, run
from ci_state import WorkflowRun, runs_on_head
from command_outcome import announce
from contract_base import Contract, Reading
from spine import decide, enforce, evaluate, halted, reasons, refusal_code

ROOT = Path(__file__).resolve().parent.parent
COMMAND = "ci:dispatch"
SUBJECT = "ci_dispatch"
POLICY = ROOT / "policies" / "runs" / "ci_dispatch"
ENTRYPOINT = "data.runs.ci_dispatch.deny"
WORKFLOW = ".github/workflows/ci.yml"
GH_DEADLINE = 60.0
OBSERVE_POLLS = 18
OBSERVE_SECONDS = 10

Gh = Callable[[list[str]], tuple[int, str]]


class DispatchRequest(Contract):
    """What ci:dispatch observed before deciding: the PR, its head, the gate and its runs."""

    pr: int | None
    head: str | None
    branch: str | None
    workflow: str
    triggers: tuple[str, ...] | None
    runs: tuple[WorkflowRun, ...] | None


class _Pull(Reading):
    number: int
    head_ref_oid: str = Field(alias="headRefOid")
    head_ref_name: str = Field(alias="headRefName")


class _GateWorkflow(Reading):
    on: dict[str, JsonValue] | list[str] | str | None = None

    @model_validator(mode="before")
    @classmethod
    def read_a_bare_on_key(cls, data: object) -> object:
        """YAML 1.1 READS A BARE `on:` AS True (A.5).

        PyYAML is a 1.1 parser, so a workflow's triggers arrive under the boolean key True and
        a model asking for "on" would see none. Renamed here, inside the model, so the parse
        still goes straight into it, as the parsing policy requires.
        """
        if not isinstance(data, dict) or True not in data:
            return data
        renamed = {key: value for key, value in data.items() if key is not True}
        return {**renamed, "on": data[True]}


def _gh(args: list[str]) -> tuple[int, str]:
    result = run(["gh", *args], deadline=GH_DEADLINE, cwd=ROOT)
    ended = result.termination
    return (ended.code if isinstance(ended, Exited) else -1), result.stdout


def _pull(gh: Gh) -> _Pull | None:
    code, out = gh(["pr", "view", "--json", "number,headRefOid,headRefName"])
    try:
        return _Pull.model_validate_json(out) if code == 0 else None
    except ValidationError:
        return None


def _triggers(root: Path = ROOT) -> tuple[str, ...] | None:
    """The gate's triggers as the committed file declares them; None when it cannot be read."""
    try:
        text = (root / WORKFLOW).read_text(encoding="utf-8")
        gate = _GateWorkflow.model_validate(yaml.safe_load(text))
    except (OSError, ValueError, yaml.YAMLError):
        return None
    if isinstance(gate.on, str):
        return (gate.on,)
    if isinstance(gate.on, list):
        return tuple(gate.on)
    if isinstance(gate.on, dict):
        return tuple(sorted(gate.on))
    return None


def _gate_ran(runs: tuple[WorkflowRun, ...] | None) -> bool:
    return any(entry.path == WORKFLOW for entry in runs or ())


def main(
    argv: Sequence[str] | None = None,
    *,
    gh: Gh = _gh,
    triggers: Callable[[], tuple[str, ...] | None] = _triggers,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """ci:dispatch -- run the gate on this branch's pull request head, then see it start."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        usage = "usage: mise run run ci:dispatch"
        stopped = halted(SUBJECT, ENTRYPOINT, POLICY, usage)
        return enforce(announce(COMMAND, stopped, "usage", usage, {}))
    pull = _pull(gh)
    head = None if pull is None else pull.head_ref_oid
    branch = None if pull is None else pull.head_ref_name
    request = DispatchRequest(
        pr=None if pull is None else pull.number,
        head=head,
        branch=branch,
        workflow=WORKFLOW,
        triggers=triggers(),
        runs=None if head is None else runs_on_head(gh, head),
    )
    observed = request.model_dump(mode="json")
    found = evaluate(request, SUBJECT, POLICY, ENTRYPOINT)
    decision = decide(found)
    if decision.action != "proceed":
        code = refusal_code(decision, "dispatch_refused")
        return enforce(announce(COMMAND, decision, code, reasons(found), observed))
    if head is None or branch is None:
        reason = "the policy allowed a dispatch with no head to dispatch on"
        stopped = halted(SUBJECT, ENTRYPOINT, POLICY, reason)
        return enforce(announce(COMMAND, stopped, "dispatch_unobservable", reason, observed))
    gh(["workflow", "run", Path(WORKFLOW).name, "--ref", branch])
    sent = {**observed, "dispatched": branch}
    for _ in range(OBSERVE_POLLS):
        sleep(OBSERVE_SECONDS)
        # GH ACCEPTING IS NOT THE GATE RUNNING: only its run, seen on the head, counts.
        if _gate_ran(runs_on_head(gh, head)):
            message = f"{WORKFLOW} now has a run on {head[:12]}"
            return enforce(announce(COMMAND, decision, "ci_dispatched", message, sent))
    reason = f"{WORKFLOW} still has no run on {head[:12]}"
    stopped = halted(SUBJECT, ENTRYPOINT, POLICY, reason)
    return enforce(announce(COMMAND, stopped, "dispatch_unobserved", reason, sent))


if __name__ == "__main__":
    raise SystemExit(main())
