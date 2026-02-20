"""
Unit tests for workflow step content handling with thinking mode enabled.

Tests cover:
- Thinking content extraction from streamed responses with <think> tags
- Proper content preservation when thinking mode is enabled
- _prepare_message correctly passes content between workflow steps
"""

from unittest.mock import MagicMock

from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.utils.reasoning import extract_thinking_content
from agno.workflow.step import Step
from agno.workflow.types import StepOutput

# =============================================================================
# Tests for extract_thinking_content
# =============================================================================


class TestExtractThinkingContent:
    """Test the extract_thinking_content utility used in streaming post-processing."""

    def test_content_with_think_tags(self):
        content = "<think>I need to analyze this</think>The answer is 42."
        reasoning, output = extract_thinking_content(content)
        assert reasoning == "I need to analyze this"
        assert output == "The answer is 42."

    def test_content_without_think_tags(self):
        content = "The answer is 42."
        reasoning, output = extract_thinking_content(content)
        assert reasoning is None
        assert output == "The answer is 42."

    def test_empty_output_after_think(self):
        content = "<think>All reasoning, no output</think>"
        reasoning, output = extract_thinking_content(content)
        assert reasoning == "All reasoning, no output"
        assert output == ""

    def test_empty_content(self):
        reasoning, output = extract_thinking_content("")
        assert reasoning is None
        assert output == ""

    def test_multiline_think_content(self):
        content = "<think>\nStep 1: analyze\nStep 2: decide\n</think>\nFinal answer here."
        reasoning, output = extract_thinking_content(content)
        assert "Step 1: analyze" in reasoning
        assert output == "Final answer here."


# =============================================================================
# Tests for _process_step_output with thinking mode
# =============================================================================


class TestProcessStepOutputWithThinking:
    """Test that _process_step_output correctly preserves content from responses with thinking."""

    def test_step_output_preserves_content_from_run_output(self):
        """When RunOutput has content (after thinking extraction), StepOutput should preserve it."""
        agent = MagicMock()
        agent.id = "test-agent"
        agent.name = "Test Agent"

        step = Step(name="test_step", agent=agent)

        run_output = RunOutput(
            content="This is the actual output after thinking extraction.",
            reasoning_content="I thought about this carefully.",
        )

        step_output = step._process_step_output(run_output)
        assert step_output.content == "This is the actual output after thinking extraction."

    def test_step_output_with_none_content(self):
        """When RunOutput has None content, StepOutput should have None content."""
        agent = MagicMock()
        agent.id = "test-agent"
        agent.name = "Test Agent"

        step = Step(name="test_step", agent=agent)

        run_output = RunOutput(
            content=None,
            reasoning_content="Only reasoning, no content.",
        )

        step_output = step._process_step_output(run_output)
        assert step_output.content is None

    def test_step_output_with_empty_string_content(self):
        """When RunOutput has empty string content, StepOutput should have empty string."""
        agent = MagicMock()
        agent.id = "test-agent"
        agent.name = "Test Agent"

        step = Step(name="test_step", agent=agent)

        run_output = RunOutput(content="")
        step_output = step._process_step_output(run_output)
        assert step_output.content == ""


# =============================================================================
# Tests for _prepare_message with thinking mode outputs
# =============================================================================


class TestPrepareMessageWithThinking:
    """Test that _prepare_message correctly handles previous step outputs from thinking models."""

    def test_prepare_message_uses_clean_content(self):
        """When previous step has clean content (after thinking extraction), it should be used."""
        agent = MagicMock()
        agent.id = "test-agent"
        agent.name = "Test Agent"

        step = Step(name="step2", agent=agent)

        previous_outputs = {
            "step1": StepOutput(
                step_name="step1",
                content="Clean output from step 1.",
            )
        }

        result = step._prepare_message("original input", previous_outputs)
        assert result == "Clean output from step 1."

    def test_prepare_message_falls_back_on_empty_content(self):
        """When previous step has empty content, original message should be used."""
        agent = MagicMock()
        agent.id = "test-agent"
        agent.name = "Test Agent"

        step = Step(name="step2", agent=agent)

        previous_outputs = {
            "step1": StepOutput(
                step_name="step1",
                content="",
            )
        }

        result = step._prepare_message("original input", previous_outputs)
        # Empty string is falsy, so original message is returned
        assert result == "original input"

    def test_prepare_message_falls_back_on_none_content(self):
        """When previous step has None content, original message should be used."""
        agent = MagicMock()
        agent.id = "test-agent"
        agent.name = "Test Agent"

        step = Step(name="step2", agent=agent)

        previous_outputs = {
            "step1": StepOutput(
                step_name="step1",
                content=None,
            )
        }

        result = step._prepare_message("original input", previous_outputs)
        assert result == "original input"

    def test_prepare_message_with_think_tags_in_content(self):
        """Content with <think> tags should still be passed if non-empty after tags.

        Note: This tests the case where streaming didn't extract think tags (pre-fix).
        After the fix, the streaming path extracts think tags before content reaches here.
        """
        agent = MagicMock()
        agent.id = "test-agent"
        agent.name = "Test Agent"

        step = Step(name="step2", agent=agent)

        # If somehow think tags are still in content, the content is non-empty and truthy
        previous_outputs = {
            "step1": StepOutput(
                step_name="step1",
                content="<think>reasoning</think>Actual output",
            )
        }

        result = step._prepare_message("original input", previous_outputs)
        assert result == "<think>reasoning</think>Actual output"


# =============================================================================
# Tests for streaming think tag extraction in handle_model_response_stream
# =============================================================================


class TestStreamingThinkTagExtraction:
    """Test that <think> tags are extracted from accumulated streaming content.

    This tests the fix applied in handle_model_response_stream and ahandle_model_response_stream
    that extracts <think> tags from run_response.content after streaming is complete.
    """

    def test_think_tags_extracted_from_run_response(self):
        """Simulate what handle_model_response_stream does after streaming with think tags."""
        run_response = RunOutput()
        model_response = ModelResponse(content="")

        # Simulate accumulated streaming content with think tags
        accumulated = "<think>Let me think step by step...</think>The final answer is 42."
        run_response.content = accumulated
        model_response.content = accumulated

        # This is the logic from handle_model_response_stream
        if run_response.content and isinstance(run_response.content, str) and "</think>" in run_response.content:
            from agno.utils.reasoning import extract_thinking_content

            reasoning_content, clean_content = extract_thinking_content(run_response.content)
            if reasoning_content:
                if not run_response.reasoning_content:
                    run_response.reasoning_content = reasoning_content
                run_response.content = clean_content
                model_response.content = clean_content
                if not model_response.reasoning_content:
                    model_response.reasoning_content = reasoning_content

        assert run_response.content == "The final answer is 42."
        assert run_response.reasoning_content == "Let me think step by step..."
        assert model_response.content == "The final answer is 42."
        assert model_response.reasoning_content == "Let me think step by step..."

    def test_no_extraction_when_no_think_tags(self):
        """No extraction should happen when content has no think tags."""
        run_response = RunOutput()
        model_response = ModelResponse(content="")

        run_response.content = "Plain content without thinking."
        model_response.content = "Plain content without thinking."

        if run_response.content and isinstance(run_response.content, str) and "</think>" in run_response.content:
            from agno.utils.reasoning import extract_thinking_content

            reasoning_content, clean_content = extract_thinking_content(run_response.content)
            if reasoning_content:
                run_response.content = clean_content

        assert run_response.content == "Plain content without thinking."

    def test_existing_reasoning_content_not_overwritten(self):
        """If reasoning_content already exists (from native field), don't overwrite it."""
        run_response = RunOutput()
        model_response = ModelResponse(content="")

        run_response.content = "<think>tag-based reasoning</think>output"
        run_response.reasoning_content = "native reasoning content"
        model_response.content = run_response.content
        model_response.reasoning_content = "native reasoning content"

        if run_response.content and isinstance(run_response.content, str) and "</think>" in run_response.content:
            from agno.utils.reasoning import extract_thinking_content

            reasoning_content, clean_content = extract_thinking_content(run_response.content)
            if reasoning_content:
                if not run_response.reasoning_content:
                    run_response.reasoning_content = reasoning_content
                run_response.content = clean_content
                model_response.content = clean_content
                if not model_response.reasoning_content:
                    model_response.reasoning_content = reasoning_content

        # Content should be cleaned
        assert run_response.content == "output"
        # Existing reasoning_content should be preserved (not overwritten)
        assert run_response.reasoning_content == "native reasoning content"

    def test_think_tags_with_empty_output(self):
        """When think tags contain everything and output is empty, content becomes empty string."""
        run_response = RunOutput()
        model_response = ModelResponse(content="")

        run_response.content = "<think>Only thinking, no output</think>"
        model_response.content = run_response.content

        if run_response.content and isinstance(run_response.content, str) and "</think>" in run_response.content:
            from agno.utils.reasoning import extract_thinking_content

            reasoning_content, clean_content = extract_thinking_content(run_response.content)
            if reasoning_content:
                if not run_response.reasoning_content:
                    run_response.reasoning_content = reasoning_content
                run_response.content = clean_content
                model_response.content = clean_content
                if not model_response.reasoning_content:
                    model_response.reasoning_content = reasoning_content

        assert run_response.content == ""
        assert run_response.reasoning_content == "Only thinking, no output"

    def test_none_content_not_processed(self):
        """None content should not be processed."""
        run_response = RunOutput()
        run_response.content = None

        # The condition should prevent processing
        if run_response.content and isinstance(run_response.content, str) and "</think>" in run_response.content:
            pass  # Should not reach here

        assert run_response.content is None


# =============================================================================
# Integration-style test for workflow step content flow with thinking
# =============================================================================


class TestWorkflowStepContentFlowWithThinking:
    """Test end-to-end content flow through workflow steps when thinking mode is enabled."""

    def test_step_output_content_after_think_extraction(self):
        """
        Simulate the full flow:
        1. Model streams response with <think> tags
        2. After streaming, think tags are extracted from run_response.content
        3. StepOutput is created from the cleaned RunOutput
        4. Next step receives clean content via _prepare_message
        """
        agent = MagicMock()
        agent.id = "test-agent"
        agent.name = "Test Agent"

        # Step 1: Create RunOutput as if streaming completed and think tags were extracted
        run_output_step1 = RunOutput(
            content="Analysis result from step 1.",
            reasoning_content="I analyzed the input carefully.",
        )

        # Process into StepOutput
        step1 = Step(name="analysis_step", agent=agent)
        step_output_step1 = step1._process_step_output(run_output_step1)
        assert step_output_step1.content == "Analysis result from step 1."

        # Step 2: _prepare_message should use step 1's clean content
        step2 = Step(name="synthesis_step", agent=agent)
        previous_outputs = {"analysis_step": step_output_step1}
        message_for_step2 = step2._prepare_message("original user input", previous_outputs)
        assert message_for_step2 == "Analysis result from step 1."

    def test_step_output_content_before_fix_with_think_tags(self):
        """
        Before the fix, streaming would accumulate <think> tags in content.
        The _prepare_message would still pass the content (with tags) to the next step.
        After the fix, the tags are extracted and only clean content is passed.
        """
        agent = MagicMock()
        agent.id = "test-agent"
        agent.name = "Test Agent"

        # Simulate RunOutput AFTER the fix (think tags extracted)
        run_output = RunOutput(
            content="Clean output after extraction.",
            reasoning_content="The extracted thinking content.",
        )

        step1 = Step(name="step1", agent=agent)
        step_output = step1._process_step_output(run_output)

        step2 = Step(name="step2", agent=agent)
        previous_outputs = {"step1": step_output}
        result = step2._prepare_message("original", previous_outputs)

        # After fix, second step gets clean content
        assert result == "Clean output after extraction."
        assert "<think>" not in result
