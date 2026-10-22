# tests/test_plan_add.py
"""Plan entries are added by a task that preserves the files' formatting (D.23).

tomlkit, the 2026 style-preserving TOML editor, appends the step to plan.toml's
[[steps]], its id to plan-ids.toml's issued and its trace entry to plan-trace.toml's
candidates -- and every comment survives. The three are validated by their
contracts together, before any is written: a refusal writes nothing.

FIXTURE FILES, COPIED: each test works on a copy of the committed fixture plan (D.53).
"""

from __future__ import annotations

import shutil
import tomllib
from pathlib import Path

import pytest

from command_outcome import CommandOutcome
from contract_base import from_document
from nonvacuous import nonempty
from plan_edit import add
from plan_models import IdLedger, PlanTrace, ProjectPlan

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "plan"
FILES = ("context/plan.toml", "context/plan-ids.toml", "context/plan-trace.toml")


def _copy(tmp_path: Path) -> Path:
    for relative in FILES:
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURE / relative, tmp_path / relative)
    return tmp_path


def _comments(root: Path) -> dict[str, list[str]]:
    return {
        r: [
            line
            for line in (root / r).read_text(encoding="utf-8").splitlines()
            if line.lstrip().startswith("#")
        ]
        for r in FILES
    }


def _plan(root: Path) -> ProjectPlan:
    return from_document(ProjectPlan, tomllib.loads((root / FILES[0]).read_text(encoding="utf-8")))


def _bytes(root: Path) -> dict[str, bytes]:
    return {r: (root / r).read_bytes() for r in FILES}


SPEC = """
[[steps]]
id = "D.99"
title = "A probe step proves the editor"
thread = "D"
depends_on = ["D.22"]
done_when = [{ kind = "task", name = "plan:add" }]

[trace]
source = "SESSION"
ref = "2026-10-02 probe"
text = "a probe step added by the test"
"""


def test_adding_a_step_keeps_every_comment(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    before = _comments(root)
    spec = tmp_path / "add.toml"
    spec.write_text(SPEC, encoding="utf-8")
    assert add([str(spec)], root=root) == 0
    after = _comments(root)
    for relative in nonempty(FILES):
        assert all(line in after[relative] for line in nonempty(before[relative])), relative
    assert "D.99" in {s.id for s in _plan(root).steps}
    ids = from_document(IdLedger, tomllib.loads((root / FILES[1]).read_text(encoding="utf-8")))
    assert "D.99" in {e.id for e in ids.issued}
    trace = (root / FILES[2]).read_text(encoding="utf-8")
    assert '"2026-10-02 probe"' in trace and '"D.99"' in trace
    from_document(PlanTrace, tomllib.loads(trace))


def test_new_entries_follow_the_files_own_style(tmp_path: Path) -> None:
    """Two-space indent, and a space inside every inline table's braces, as written by hand."""
    root = _copy(tmp_path)
    spec = tmp_path / "add.toml"
    spec.write_text(SPEC, encoding="utf-8")
    assert add([str(spec)], root=root) == 0
    # ONLY THE NEW BLOCK: D.23's own hand-written evidence carries this very line.
    block = (root / FILES[0]).read_text(encoding="utf-8").split('id = "D.99"', 1)[1]
    assert '\n  { kind = "task", name = "plan:add" },' in block
    assert '  { id = "D.99", first_title = ' in (root / FILES[1]).read_text(encoding="utf-8")
    assert '  { source = "SESSION", ref = "2026-10-02 probe"' in (root / FILES[2]).read_text(
        encoding="utf-8"
    )


def test_a_duplicate_id_writes_nothing(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    before = _bytes(root)
    spec = tmp_path / "add.toml"
    spec.write_text(SPEC.replace('"D.99"', '"D.12"'), encoding="utf-8")
    assert add([str(spec)], root=root) == 2
    assert _bytes(root) == before


def test_a_because_keyed_by_a_step_id_round_trips(tmp_path: Path) -> None:
    """A step id holds a dot, so as a key it must be quoted, or TOML reads it as dotted (D.51)."""
    root = _copy(tmp_path)
    with_because = SPEC.replace(
        'depends_on = ["D.22"]\n',
        'depends_on = ["D.22"]\nbecause = { "D.22" = "the probe reads a plan step by task" }\n',
    )
    assert with_because != SPEC
    spec = tmp_path / "add.toml"
    spec.write_text(with_because, encoding="utf-8")
    assert add([str(spec)], root=root) == 0
    probe = next(s for s in _plan(root).steps if s.id == "D.99")
    assert probe.because == {"D.22": "the probe reads a plan step by task"}
    block = (root / FILES[0]).read_text(encoding="utf-8").split('id = "D.99"', 1)[1]
    assert 'because = { "D.22" = "the probe reads a plan step by task" }' in block


THREAD_SPEC = """
[[threads]]
id = "Z"
title = "A probe thread proves the editor"

[[steps]]
id = "Z.1"
title = "A probe step in a thread the same spec declares"
thread = "Z"
depends_on = ["D.12"]
done_when = [{ kind = "task", name = "plan:add" }]

[trace]
source = "SESSION"
ref = "2026-10-20 thread probe"
text = "a probe thread and its step added by the test"
"""


def test_a_spec_adds_a_new_thread_with_its_steps(tmp_path: Path) -> None:
    """A thread declared in the spec is written with the step that names it (D.272)."""
    root = _copy(tmp_path)
    spec = tmp_path / "add.toml"
    spec.write_text(THREAD_SPEC, encoding="utf-8")
    assert add([str(spec)], root=root) == 0
    plan = _plan(root)
    assert ("Z", "A probe thread proves the editor") in {(t.id, t.title) for t in plan.threads}
    assert "D" in {t.id for t in plan.threads}
    assert next(s for s in plan.steps if s.id == "Z.1").thread == "Z"
    ids = from_document(IdLedger, tomllib.loads((root / FILES[1]).read_text(encoding="utf-8")))
    assert "Z.1" in {e.id for e in ids.issued}


def test_an_existing_thread_id_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A thread the plan already declares is refused as data, and nothing is written."""
    root = _copy(tmp_path)
    before = _bytes(root)
    spec = tmp_path / "add.toml"
    spec.write_text(THREAD_SPEC.replace('"Z"', '"D"'), encoding="utf-8")
    assert add([str(spec)], root=root) == 2
    outcome = CommandOutcome.model_validate_json(capsys.readouterr().out)
    assert outcome.code == "thread_taken"
    assert _bytes(root) == before


def test_a_step_naming_an_undeclared_thread_is_refused_as_data(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A step in a thread neither the plan nor the spec declares is a typed refusal."""
    root = _copy(tmp_path)
    before = _bytes(root)
    spec = tmp_path / "add.toml"
    spec.write_text(SPEC.replace('thread = "D"', 'thread = "Y"'), encoding="utf-8")
    assert add([str(spec)], root=root) == 2
    outcome = CommandOutcome.model_validate_json(capsys.readouterr().out)
    assert outcome.code == "thread_undeclared"
    assert outcome.data["step"] == "D.99"
    assert outcome.data["thread"] == "Y"
    assert _bytes(root) == before
