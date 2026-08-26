"""Python 3.9 compatibility guards.

The package advertises requires-python >=3.9, and CI runs newer interpreters -
so a 3.10-only construct ships silently and a 3.9 user gets a clean install
that dies at import. These guards catch the known construct classes
statically, on any interpreter:

- 3.10+ syntax (match statements, parenthesized context managers) via an AST
  parse pinned to feature_version 3.9;
- field(kw_only=...) / dataclass(slots=...) - runtime TypeError on 3.9;
- PEP 604 unions (X | None) in files WITHOUT `from __future__ import
  annotations` - evaluated at import time on 3.9, TypeError.

Plus round-trips for BaseRunOutputEvent.event_index, which is deliberately a
plain class attribute instead of a field(kw_only=True) for exactly this
reason - its serialization is carried explicitly and must not regress.
"""

import ast
import pathlib
import re

import pytest

PACKAGE_ROOT = pathlib.Path(__file__).resolve().parents[2] / "agno"

PEP604_ANNOTATION = re.compile(r":\s*[A-Za-z_][A-Za-z0-9_\[\], .]*\s\|\s*[A-Za-z_\"']")


def _source_files():
    return sorted(PACKAGE_ROOT.rglob("*.py"))


class TestPy39Syntax:
    def test_every_module_parses_as_39(self):
        failures = []
        for path in _source_files():
            try:
                ast.parse(path.read_text(), feature_version=(3, 9))
            except SyntaxError as e:
                failures.append(f"{path}:{e.lineno}: {e.msg}")
        assert not failures, "3.10+ syntax in a package that supports 3.9:\n" + "\n".join(failures)

    def test_no_kw_only_or_slots_dataclass_params(self):
        """field(kw_only=...) and @dataclass(slots=...) parse fine on 3.9 and
        then raise TypeError at class-creation time - the worst failure mode
        (install succeeds, import dies)."""
        offenders = []
        for path in _source_files():
            # Comments legitimately discuss these constructs - strip them
            # (and docstrings) so only actual usage trips the guard
            src = re.sub(r"#.*", "", path.read_text())
            src = re.sub(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'', "", src)
            if re.search(r"\bkw_only\s*=", src) or re.search(r"dataclass\([^)]*slots\s*=", src):
                offenders.append(str(path))
        assert not offenders, f"3.10-only dataclass parameters: {offenders}"

    def test_evaluated_pep604_unions_have_future_import(self):
        """`X | None` annotations in class bodies and signatures are evaluated
        at import time UNLESS the module has `from __future__ import
        annotations`. Files using the syntax must carry the shield."""
        offenders = []
        for path in _source_files():
            src = path.read_text()
            if PEP604_ANNOTATION.search(src) and "from __future__ import annotations" not in src:
                # Confirm at least one hit is a real annotation, not a string
                # or comment: strip comments and docstrings crudely first
                stripped = re.sub(r"#.*", "", src)
                stripped = re.sub(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'', "", stripped)
                if PEP604_ANNOTATION.search(stripped):
                    offenders.append(str(path))
        assert not offenders, (
            f"PEP 604 unions without `from __future__ import annotations` (import-time TypeError on 3.9): {offenders}"
        )


class TestEventIndexRoundTrip:
    """event_index is a plain class attribute (not a dataclass field), so
    to_dict/from_dict carry it explicitly - pin the full round trip."""

    def test_not_a_dataclass_field(self):
        from dataclasses import fields

        from agno.run.base import BaseRunOutputEvent

        assert "event_index" not in {f.name for f in fields(BaseRunOutputEvent)}, (
            "event_index as a field needs kw_only=True, which is 3.10-only"
        )

    def test_default_is_none_and_assignable(self):
        from agno.run.agent import RunContentEvent

        event = RunContentEvent(content="a", run_id="r1")
        assert event.event_index is None
        event.event_index = 7
        assert event.event_index == 7
        # The class default is untouched by instance assignment
        assert RunContentEvent(content="b", run_id="r1").event_index is None

    def test_to_dict_carries_stamped_index_and_omits_none(self):
        from agno.run.agent import RunContentEvent

        stamped = RunContentEvent(content="a", run_id="r1")
        stamped.event_index = 5
        assert stamped.to_dict()["event_index"] == 5

        unstamped = RunContentEvent(content="a", run_id="r1")
        assert "event_index" not in unstamped.to_dict(), "None must not change the storage shape"

    def test_from_dict_restores_the_index(self):
        from agno.run.agent import RunContentEvent

        data = {"content": "a", "run_id": "r1", "event_index": 12}
        event = RunContentEvent.from_dict(data)
        assert event.event_index == 12

    def test_from_dict_without_index_defaults_none(self):
        from agno.run.agent import RunContentEvent

        assert RunContentEvent.from_dict({"content": "a", "run_id": "r1"}).event_index is None

    def test_full_round_trip_survives(self):
        from agno.run.agent import RunContentEvent

        original = RunContentEvent(content="a", run_id="r1")
        original.event_index = 41
        assert RunContentEvent.from_dict(original.to_dict()).event_index == 41

    def test_subclass_with_required_positional_fields_constructs(self):
        """The reason the attribute cannot be a plain defaulted field: a
        defaulted base field before a required subclass field is a TypeError
        at class definition on every Python version."""
        from dataclasses import dataclass

        from agno.run.base import BaseRunOutputEvent

        @dataclass
        class SampleEvent(BaseRunOutputEvent):
            required_payload: str

        event = SampleEvent(required_payload="x")
        assert event.event_index is None
        event.event_index = 3
        assert event.to_dict()["event_index"] == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
