"""Tests for A2A streaming with output_schema (Pydantic models).

Verifies fix for issue #6850: TypeError when streaming agents that have
output_schema set to a Pydantic model.
"""

import importlib
import json

from pydantic import BaseModel, Field

# Import _serialize_content directly from utils without triggering
# the a2a package chain via __init__.py.
_utils = importlib.import_module("agno.os.interfaces.a2a.utils")
_serialize_content = _utils._serialize_content


class AnalysisResult(BaseModel):
    category: str = Field(..., description="Category")
    confidence: float = Field(..., description="Confidence score")
    summary: str = Field(..., description="Brief summary")


class TestSerializeContent:
    """Test the _serialize_content helper used in A2A streaming."""

    def test_pydantic_model_returns_json(self):
        model = AnalysisResult(category="test", confidence=0.95, summary="A test result")
        result = _serialize_content(model)
        parsed = json.loads(result)
        assert parsed["category"] == "test"
        assert parsed["confidence"] == 0.95
        assert parsed["summary"] == "A test result"

    def test_dict_returns_json(self):
        d = {"key": "value", "num": 42}
        result = _serialize_content(d)
        assert json.loads(result) == d

    def test_string_passthrough(self):
        assert _serialize_content("hello world") == "hello world"

    def test_number_converted_to_str(self):
        assert _serialize_content(123) == "123"

    def test_accumulation_with_pydantic_model(self):
        """Reproduces the original bug: accumulating content from a Pydantic model."""
        accumulated = ""
        model = AnalysisResult(category="bug", confidence=0.99, summary="Repro")
        serialized = _serialize_content(model)
        # This line used to raise: TypeError: can only concatenate str (not "AnalysisResult") to str
        accumulated += serialized
        assert isinstance(accumulated, str)
        parsed = json.loads(accumulated)
        assert parsed["category"] == "bug"
