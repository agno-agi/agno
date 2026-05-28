"""
Unit tests for StepInput file serialization.

Tests cover:
- to_dict(): File objects are serialized via .to_dict()
- Roundtrip serialization (no data loss)
"""

import pytest

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
