"""StudioTools answers in two shapes, and the Studio cookbook has to say so.

Control-plane tools return the StudioResult envelope. The run tools return the
runner's flat payload, whose error is a prose string with no code -- except on
the pinned-preview gate, which refuses in the envelope. A driver written
against a doc that promises one shape everywhere crashes on
``result["error"]["code"]`` the first time a run id fails to resolve.
"""

import json
from pathlib import Path

import pytest

from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.registry import Registry
from agno.tools.studio import StudioTools

README = Path(__file__).resolve().parents[5] / "cookbook" / "05_agent_os" / "22_studio" / "README.md"


@pytest.fixture
def studio(tmp_path):
    db = SqliteDb(id="shape-test-db", db_file=str(tmp_path / "shape.db"))
    registry = Registry(name="Shape Test Registry", models=[OpenAIResponses(id="gpt-5.4")], dbs=[db])
    return StudioTools(registry=registry, db=db, schedules=True)


def _envelope_section() -> str:
    """The README paragraphs describing the result shape, up to the next heading."""
    if not README.exists():
        pytest.skip("cookbook not present in this checkout")
    text = README.read_text(encoding="utf-8")
    anchor = text.index("`StudioResult` JSON envelope")
    # From the top of the sentence, not the phrase: the claim under test is the
    # quantifier in front of it.
    start = text.rfind("\n", 0, anchor) + 1
    end = text.index("\n## ", anchor)
    return text[start:end]


def test_control_plane_tools_answer_in_the_envelope(studio):
    result = json.loads(studio.get_component("nope"))
    assert result["ok"] is False
    assert result["error"]["code"] == "component_not_found"


def test_run_tools_answer_flat_with_a_prose_error(studio):
    """The doc must not promise error.code here: this error is a bare string."""
    result = json.loads(studio.run_agent("nope", "hi"))
    assert "ok" not in result
    assert isinstance(result["error"], str)


def test_the_preview_gate_answers_in_the_envelope(studio):
    result = json.loads(studio.run_agent("nope", "hi", version=1))
    assert result["ok"] is False
    assert result["error"]["code"] == "component_not_found"


def test_mounted_schedule_tools_answer_flat(studio):
    """Mounted, so the toolkit's registered function is the only call surface."""
    result = json.loads(studio.functions["list_schedules"].entrypoint())
    assert "ok" not in result
    assert "schedules" in result


def test_readme_does_not_promise_the_envelope_everywhere():
    section = _envelope_section()
    assert "Every tool returns one" not in section


def test_readme_names_the_run_tools_as_the_exception():
    section = _envelope_section()
    for name in ("run_agent", "run_team", "run_workflow"):
        assert name in section
    assert "flat" in section
