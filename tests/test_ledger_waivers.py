# tests/test_ledger_waivers.py
"""A project born sealed inherits no waiver from the template (A.2).

The template shipped its own registry, waiving record 2430 of another ledger, so this project's
runs:verify refused a waiver naming a record it never wrote. Its ledger began sealed, so no record
of its own is unsigned after signing, and its registry has nothing to account for.
"""

from __future__ import annotations

from run_ledger import declared_waivers


def test_a_project_born_sealed_inherits_no_waiver() -> None:
    """A.2: the committed registry, read as runs:verify reads it, waives no record at all."""
    waivers = declared_waivers()
    assert waivers == (), waivers
