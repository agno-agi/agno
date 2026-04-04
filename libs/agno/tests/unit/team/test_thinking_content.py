"""
Unit tests for team streaming content handling with thinking mode enabled.

Tests cover:
- Think tag extraction from accumulated streaming content in team _response.py
- Correct behavior when reasoning_content already exists (native reasoning preserved)
- No-op behavior for non-thinking model content
- Proper content/reasoning_content propagation from full_model_response to run_response
"""

from agno.models.response import ModelResponse
from agno.run.team import TeamRunOutput
from agno.utils.reasoning import extract_thinking_content

# =============================================================================
# Tests for team streaming think tag extraction
# =============================================================================


class TestTeamStreamingThinkTagExtraction:
    """Test think tag extraction logic applied in team _handle_model_response_stream.

    This mirrors the extraction block added at team/_response.py lines ~1035-1048 (sync)
    and ~1204-1214 (async). The logic operates on full_model_response before its values
    are copied into run_response.
    """

    def _apply_extraction(self, full_model_response: ModelResponse) -> None:
        """Reproduce the exact extraction logic from team/_response.py."""
        if (
            full_model_response.content
            and isinstance(full_model_response.content, str)
            and "</think>" in full_model_response.content
        ):
            reasoning_content, clean_content = extract_thinking_content(full_model_response.content)
            if reasoning_content:
                full_model_response.content = clean_content
                if not full_model_response.reasoning_content:
                    full_model_response.reasoning_content = reasoning_content

    def _propagate_to_run_response(self, full_model_response: ModelResponse, run_response: TeamRunOutput) -> None:
        """Reproduce the propagation logic from team/_response.py lines ~1050-1060."""
        if full_model_response.content is not None:
            run_response.content = full_model_response.content
        if full_model_response.reasoning_content is not None:
            run_response.reasoning_content = full_model_response.reasoning_content

    def test_think_tags_extracted_and_propagated(self):
        """Content with <think> tags should be cleaned; reasoning propagated to run_response."""
        full_model_response = ModelResponse(content="<think>Step-by-step reasoning here</think>Final answer.")
        run_response = TeamRunOutput()

        self._apply_extraction(full_model_response)
        self._propagate_to_run_response(full_model_response, run_response)

        assert full_model_response.content == "Final answer."
        assert full_model_response.reasoning_content == "Step-by-step reasoning here"
        assert run_response.content == "Final answer."
        assert run_response.reasoning_content == "Step-by-step reasoning here"

    def test_no_think_tags_content_unchanged(self):
        """Content without <think> tags should pass through unmodified."""
        full_model_response = ModelResponse(content="Plain answer with no thinking.")
        run_response = TeamRunOutput()

        self._apply_extraction(full_model_response)
        self._propagate_to_run_response(full_model_response, run_response)

        assert run_response.content == "Plain answer with no thinking."
        assert run_response.reasoning_content is None

    def test_existing_reasoning_content_preserved(self):
        """Native reasoning_content (from model API field) should not be overwritten by tag extraction."""
        full_model_response = ModelResponse(
            content="<think>tag-based reasoning</think>output",
            reasoning_content="native reasoning from API",
        )
        run_response = TeamRunOutput()

        self._apply_extraction(full_model_response)
        self._propagate_to_run_response(full_model_response, run_response)

        assert full_model_response.content == "output"
        # Native reasoning preserved
        assert full_model_response.reasoning_content == "native reasoning from API"
        assert run_response.reasoning_content == "native reasoning from API"

    def test_think_tags_with_empty_output(self):
        """When all content is inside <think> tags, content becomes empty string."""
        full_model_response = ModelResponse(content="<think>All reasoning, no output</think>")
        run_response = TeamRunOutput()

        self._apply_extraction(full_model_response)
        self._propagate_to_run_response(full_model_response, run_response)

        assert run_response.content == ""
        assert run_response.reasoning_content == "All reasoning, no output"

    def test_none_content_skipped(self):
        """None content should not be processed at all."""
        full_model_response = ModelResponse(content=None)
        run_response = TeamRunOutput()

        self._apply_extraction(full_model_response)
        # content is None, so propagation condition `content is not None` is False
        self._propagate_to_run_response(full_model_response, run_response)

        assert run_response.content is None
        assert run_response.reasoning_content is None

    def test_multiline_think_content(self):
        """Multiline reasoning inside <think> tags should be extracted correctly."""
        full_model_response = ModelResponse(
            content="<think>\nLine 1: analyze\nLine 2: decide\n</think>\nThe result is X."
        )
        run_response = TeamRunOutput()

        self._apply_extraction(full_model_response)
        self._propagate_to_run_response(full_model_response, run_response)

        assert "Line 1: analyze" in run_response.reasoning_content
        assert "Line 2: decide" in run_response.reasoning_content
        assert run_response.content == "The result is X."

    def test_non_string_content_skipped(self):
        """Non-string content (e.g., dict for structured output) should not be processed."""
        full_model_response = ModelResponse(content={"key": "value"})
        run_response = TeamRunOutput()

        self._apply_extraction(full_model_response)
        self._propagate_to_run_response(full_model_response, run_response)

        assert run_response.content == {"key": "value"}
        assert run_response.reasoning_content is None

    def test_guard_condition_skip_for_no_close_tag(self):
        """Content with <think> but no </think> should not be processed."""
        full_model_response = ModelResponse(content="<think>incomplete thinking without close tag")
        run_response = TeamRunOutput()

        self._apply_extraction(full_model_response)
        self._propagate_to_run_response(full_model_response, run_response)

        assert run_response.content == "<think>incomplete thinking without close tag"
        assert run_response.reasoning_content is None
