"""Test that Anthropic cumulative usage metrics are handled correctly."""

from typing import Any, Dict, Iterator, List, Optional, Type, Union

from agno.models.base import Model
from agno.models.message import Message
from agno.models.metrics import Metrics
from agno.models.response import ModelResponse


class FakeAnthropicModel(Model):
    """
    Fake model that simulates Anthropic's cumulative usage behavior.

    Anthropic returns cumulative usage across multiple streaming events during tool calls:
    - Event 1: Usage(input: 63k, output: 2)
    - Event 2: Usage(input: 64k, output: 217) <- CUMULATIVE (includes Event 1)
    - Event 3: Usage(input: 65k, output: 2) <- CUMULATIVE (includes Event 1 + Event 2)

    Without the fix, Agno would accumulate these: 63k + 64k + 65k = 192k tokens
    With the fix, Agno should replace them: final = 65k tokens
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.event_count = 0

    def invoke(
        self,
        messages: List[Message],
        assistant_message: Optional[Message] = None,
        response_format: Optional[Union[Dict, Type]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[Any] = None,
    ) -> ModelResponse:
        return ModelResponse()

    async def ainvoke(
        self,
        messages: List[Message],
        assistant_message: Optional[Message] = None,
        response_format: Optional[Union[Dict, Type]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[Any] = None,
    ) -> ModelResponse:
        return ModelResponse()

    def invoke_stream(
        self,
        messages: List[Message],
        assistant_message: Optional[Message] = None,
        response_format: Optional[Union[Dict, Type]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[Any] = None,
    ) -> Iterator[ModelResponse]:
        """
        Simulate Anthropic's streaming behavior with cumulative usage.

        Returns 3 events with cumulative usage metrics:
        1. input: 63325, output: 2
        2. input: 64197, output: 217 (cumulative)
        3. input: 64911, output: 2 (cumulative)
        """
        # Event 1: First tool call
        response1 = ModelResponse()
        response1.content = "Tool call 1"
        metrics1 = Metrics()
        metrics1.input_tokens = 63325
        metrics1.output_tokens = 2
        metrics1.total_tokens = 63327
        response1.response_usage = metrics1
        response1._is_cumulative_usage = True  # Mark as cumulative
        yield response1

        # Event 2: Tool result and next turn (CUMULATIVE - includes Event 1)
        response2 = ModelResponse()
        response2.content = "Response after tool"
        metrics2 = Metrics()
        metrics2.input_tokens = 64197  # 63325 + ~872 new tokens
        metrics2.output_tokens = 217
        metrics2.total_tokens = 64414
        response2.response_usage = metrics2
        response2._is_cumulative_usage = True  # Mark as cumulative
        yield response2

        # Event 3: Another tool call (CUMULATIVE - includes Event 1 + Event 2)
        response3 = ModelResponse()
        response3.content = "Tool call 2"
        metrics3 = Metrics()
        metrics3.input_tokens = 64911  # 64197 + ~714 new tokens
        metrics3.output_tokens = 2
        metrics3.total_tokens = 64913
        response3.response_usage = metrics3
        response3._is_cumulative_usage = True  # Mark as cumulative
        yield response3

    async def ainvoke_stream(
        self,
        messages: List[Message],
        assistant_message: Optional[Message] = None,
        response_format: Optional[Union[Dict, Type]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[Any] = None,
    ):
        for response in self.invoke_stream(
            messages, assistant_message, response_format, tools, tool_choice, run_response
        ):
            yield response

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return ModelResponse()


def test_anthropic_cumulative_usage_not_inflated():
    """
    Test that Anthropic's cumulative usage metrics are replaced, not accumulated.

    This reproduces the bug where Agno would inflate token counts by accumulating
    cumulative usage totals from multiple streaming events.

    Expected: Final metrics should be 64911 input tokens (from last event)
    Bug behavior: Would be 192433 (63325 + 64197 + 64911) if accumulating
    """
    model = FakeAnthropicModel(id="fake-anthropic")

    # Simulate streaming with cumulative usage
    messages = [Message(role="user", content="Test")]
    assistant_message = Message(role="assistant")

    # Process the stream (this will call _populate_assistant_message multiple times)
    from agno.models.base import MessageData

    stream_data = MessageData()

    responses = list(
        model.process_response_stream(
            messages=messages,
            assistant_message=assistant_message,
            stream_data=stream_data,
        )
    )

    # Verify we got 3 responses
    assert len(responses) == 3, f"Expected 3 responses, got {len(responses)}"

    # The assistant_message should have the final cumulative usage (not accumulated)
    # Expected: 64911 input tokens (from last event)
    # Bug would produce: 192433 (sum of all events)
    assert assistant_message.metrics.input_tokens == 64911, (
        f"Expected 64911 input tokens, got {assistant_message.metrics.input_tokens}"
    )

    # Verify output tokens are also from the last event
    assert assistant_message.metrics.output_tokens == 2, (
        f"Expected 2 output tokens, got {assistant_message.metrics.output_tokens}"
    )

    # Verify total tokens
    assert assistant_message.metrics.total_tokens == 64913, (
        f"Expected 64913 total tokens, got {assistant_message.metrics.total_tokens}"
    )


def test_non_cumulative_usage_still_accumulates():
    """
    Test that non-Anthropic providers (without _is_cumulative_usage flag)
    still accumulate usage metrics correctly.

    This ensures we didn't break the behavior for OpenAI, Gemini, etc.
    """

    class FakeOpenAIModel(Model):
        """Simulates OpenAI which only returns usage in final chunk."""

        def invoke(self, *args, **kwargs) -> ModelResponse:
            return ModelResponse()

        async def ainvoke(self, *args, **kwargs) -> ModelResponse:
            return ModelResponse()

        def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
            # First chunks have no usage
            yield ModelResponse(content="chunk1")
            yield ModelResponse(content="chunk2")

            # Final chunk has usage
            response = ModelResponse(content="chunk3")
            metrics = Metrics()
            metrics.input_tokens = 1000
            metrics.output_tokens = 100
            metrics.total_tokens = 1100
            response.response_usage = metrics
            # NOTE: No _is_cumulative_usage flag - should accumulate
            yield response

        async def ainvoke_stream(self, *args, **kwargs):
            for response in self.invoke_stream(*args, **kwargs):
                yield response

        def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
            return ModelResponse()

        def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
            return ModelResponse()

    model = FakeOpenAIModel(id="fake-openai")
    messages = [Message(role="user", content="Test")]
    assistant_message = Message(role="assistant")

    from agno.models.base import MessageData

    stream_data = MessageData()

    list(
        model.process_response_stream(
            messages=messages,
            assistant_message=assistant_message,
            stream_data=stream_data,
        )
    )

    # For OpenAI-style providers, usage should be accumulated (but only one event has usage)
    assert assistant_message.metrics.input_tokens == 1000, (
        f"Expected 1000 input tokens, got {assistant_message.metrics.input_tokens}"
    )
    assert assistant_message.metrics.output_tokens == 100, (
        f"Expected 100 output tokens, got {assistant_message.metrics.output_tokens}"
    )
