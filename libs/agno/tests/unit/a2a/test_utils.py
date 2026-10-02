"""Unit tests for A2A serialization utils."""

import json

from pydantic import BaseModel

from agno.os.interfaces.a2a.utils import _stringify_content, map_run_output_to_a2a_task
from agno.run.agent import RunOutput
from agno.run.base import RunStatus


class _SampleModel(BaseModel):
    query: str
    assumptions: list[str]


class TestStringifyContent:
    def test_pydantic_model_is_dumped_as_json(self):
        model = _SampleModel(query="select 1 from something", assumptions=["a", "b"])
        result = _stringify_content(model)
        # Round-trips through json.loads — would fail with plain str(model)
        assert json.loads(result) == {"query": "select 1 from something", "assumptions": ["a", "b"]}

    def test_string_is_passed_through(self):
        assert _stringify_content("hello") == "hello"

    def test_non_string_non_model_falls_back_to_str(self):
        assert _stringify_content(42) == "42"
        assert _stringify_content({"a": 1}) == "{'a': 1}"


class TestMapRunOutputToA2ATaskJSONContent:
    def test_pydantic_content_produces_json_text_part(self):
        """Non-streaming :send path must emit JSON, not BaseModel.__repr__."""
        model = _SampleModel(query="select 1 from something", assumptions=["a", "b"])
        run_output = RunOutput(
            run_id="run-1",
            session_id="sess-1",
            content=model,
            status=RunStatus.completed,
        )

        task = map_run_output_to_a2a_task(run_output)

        assert len(task.history) == 1
        parts = task.history[0].parts
        assert len(parts) == 1
        text = parts[0].root.text
        # The fix: text is valid JSON matching the model, not a Python repr.
        assert json.loads(text) == {"query": "select 1 from something", "assumptions": ["a", "b"]}

    def test_string_content_is_unchanged(self):
        run_output = RunOutput(
            run_id="run-1",
            session_id="sess-1",
            content="plain text",
            status=RunStatus.completed,
        )
        task = map_run_output_to_a2a_task(run_output)
        assert task.history[0].parts[0].root.text == "plain text"

