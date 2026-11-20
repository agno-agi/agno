"""
Unit tests for StepInput serialization.

Tests cover:
- to_dict(): File objects are serialized via .to_dict()
- to_dict() / from_dict(): Falsy previous_step_content and sibling fields are preserved
- Roundtrip serialization (no data loss)
"""

import json
from typing import Any

import pytest
from pydantic import BaseModel

from agno.media import File
from agno.workflow.types import StepInput, StepRequirement


@pytest.fixture
def sample_file():
    return File(id="test_sample_id", url="https://example.com/test-file.pdf", format="pdf", filename="test-file.pdf")


class TestStepInputFileSerialization:
    def test_to_dict_produces_dict_not_file_object(self, sample_file):
        """File objects should be serialized via .to_dict(), not copied raw."""
        step_input = StepInput(input="process this", files=[sample_file])
        result = step_input.to_dict()

        assert result["files"] is not None
        assert len(result["files"]) == 1
        assert isinstance(result["files"][0], dict)
        assert result["files"][0]["id"] == "test_sample_id"
        assert result["files"][0]["url"] == "https://example.com/test-file.pdf"
        assert result["files"][0]["format"] == "pdf"
        assert result["files"][0]["filename"] == "test-file.pdf"

    def test_to_dict_multiple_files(self):
        """Multiple files should all be serialized to dicts."""
        files = [
            File(id="f1", url="https://example.com/a.pdf", format="pdf"),
            File(id="f2", url="https://example.com/b.csv", format="csv"),
        ]
        step_input = StepInput(input="batch", files=files)
        result = step_input.to_dict()

        assert len(result["files"]) == 2
        assert all(isinstance(f, dict) for f in result["files"])
        assert result["files"][0]["id"] == "f1"
        assert result["files"][0]["format"] == "pdf"
        assert result["files"][1]["id"] == "f2"
        assert result["files"][1]["format"] == "csv"

    def test_to_dict_no_files_returns_none(self):
        """Absent files should serialize as None."""
        step_input = StepInput(input="hello")
        assert step_input.to_dict()["files"] is None

    def test_roundtrip_preserves_file_data(self, sample_file):
        """Files should survive to_dict -> from_dict without data loss."""
        original = StepInput(input="process", files=[sample_file])

        serialized = original.to_dict()
        restored = StepInput.from_dict(serialized)

        assert restored.files is not None
        assert len(restored.files) == 1
        assert restored.files[0].id == "test_sample_id"
        assert restored.files[0].url == "https://example.com/test-file.pdf"
        assert restored.files[0].format == "pdf"
        assert restored.files[0].filename == "test-file.pdf"


class _SampleModel(BaseModel):
    label: str
    count: int


class TestStepInputPreviousStepContentSerialization:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("", ""),
            (0, "0"),
            (False, "False"),
            (0.0, "0.0"),
            ([], "[]"),
            ({}, "{}"),
        ],
    )
    def test_to_dict_preserves_falsy_previous_step_content(self, value: Any, expected: str):
        """Falsy non-None previous_step_content values must not be dropped as None."""
        step_input = StepInput(input="run", previous_step_content=value)

        serialized = step_input.to_dict()
        assert serialized["previous_step_content"] == expected

        restored = StepInput.from_dict(json.loads(json.dumps(serialized)))
        assert restored.previous_step_content == expected

    def test_to_dict_keeps_none_previous_step_content_as_none(self):
        """None previous_step_content should continue to serialize as None."""
        step_input = StepInput(input="run", previous_step_content=None)

        serialized = step_input.to_dict()
        assert serialized["previous_step_content"] is None

        restored = StepInput.from_dict(json.loads(json.dumps(serialized)))
        assert restored.previous_step_content is None

    def test_to_dict_preserves_truthy_dict_and_model_previous_step_content(self):
        """Existing dict and BaseModel serialization branches remain unchanged."""
        model_input = StepInput(input="run", previous_step_content=_SampleModel(label="ok", count=2))
        dict_input = StepInput(input="run", previous_step_content={"k": "v"})

        assert json.loads(model_input.to_dict()["previous_step_content"]) == {"label": "ok", "count": 2}
        assert json.loads(dict_input.to_dict()["previous_step_content"]) == {"k": "v"}

    def test_step_requirement_roundtrip_preserves_falsy_step_input_fields(self):
        """HITL StepRequirement roundtrip preserves falsy previous_step_content, input, and additional_data."""
        req = StepRequirement(
            step_id="step-1",
            step_name="review",
            step_input=StepInput(input="", previous_step_content="", additional_data={}),
        )

        payload = json.loads(json.dumps(req.to_dict()))
        restored = StepRequirement.from_dict(payload)

        assert restored.step_input is not None
        assert restored.step_input.input == ""
        assert restored.step_input.previous_step_content == ""
        assert restored.step_input.additional_data == {}
