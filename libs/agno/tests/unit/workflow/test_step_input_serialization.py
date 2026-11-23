"""
Unit tests for StepInput serialization.

Tests cover:
- to_dict(): File objects are serialized via .to_dict()
- to_dict(): falsy previous_step_content values are preserved
- Roundtrip serialization (no data loss)
"""

import json
from datetime import datetime

import pytest

from agno.db.utils import json_serializer
from agno.media import File
from agno.workflow.types import StepInput


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


class TestStepInputPreviousStepContentSerialization:
    @pytest.mark.parametrize("content", ["", 0, False, 0.0])
    def test_roundtrip_preserves_previous_step_content(self, content):
        """Falsy content is a meaningful step result and must keep its value and type."""
        restored = StepInput.from_dict(StepInput(input="run", previous_step_content=content).to_dict())
        assert restored.previous_step_content == content
        assert type(restored.previous_step_content) is type(content)

    @pytest.mark.parametrize("content", ["", 0, False, 0.0])
    def test_roundtrip_keeps_falsy_previous_step_content_falsy(self, content):
        restored = StepInput.from_dict(StepInput(input="run", previous_step_content=content).to_dict())
        assert not restored.previous_step_content

    def test_to_dict_keeps_none_previous_step_content(self):
        step_input = StepInput(input="run", previous_step_content=None)
        assert step_input.to_dict()["previous_step_content"] is None

    @pytest.mark.parametrize("content", [False, 0, 0.0])
    def test_json_roundtrip_preserves_falsy_types(self, content):
        """Values must keep their type through a real JSON encode/decode, as when stored in a DB."""
        encoded = json_serializer(StepInput(input="run", previous_step_content=content).to_dict())
        restored = StepInput.from_dict(json.loads(encoded))
        assert restored.previous_step_content == content
        assert type(restored.previous_step_content) is type(content)
        assert not restored.previous_step_content

    @pytest.mark.parametrize("content, expected", [(42, "42"), ("result", "result"), (float("inf"), "inf")])
    def test_truthy_scalars_keep_string_form(self, content, expected):
        """Truthy values keep the existing str() form, so strict JSON encoding still works."""
        data = StepInput(input="run", previous_step_content=content).to_dict()
        assert data["previous_step_content"] == expected
        json.dumps(data, allow_nan=False)

    @pytest.mark.parametrize("content", [[], (), set()])
    def test_falsy_non_scalars_keep_none_fallback(self, content):
        """Falsy values outside the scalar types still restore as None, not a truthy string."""
        restored = StepInput.from_dict(StepInput(input="run", previous_step_content=content).to_dict())
        assert restored.previous_step_content is None

    def test_list_with_datetime_still_encodes(self):
        """Lists stay stringified so plain json.dumps works on non-JSON elements."""
        content = [datetime(2026, 1, 1)]
        encoded = json.dumps(StepInput(input="run", previous_step_content=content).to_dict())
        assert json.loads(encoded)["previous_step_content"] == str(content)
