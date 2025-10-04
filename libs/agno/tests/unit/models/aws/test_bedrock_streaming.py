"""Unit tests for AWS Bedrock streaming response parsing, specifically tool call handling."""

from agno.models.aws import AwsBedrock


def test_parse_streaming_tool_call_with_single_chunk():
    """Test parsing a tool call where arguments come in a single chunk."""
    model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0")

    # Simulate streaming chunks from Bedrock
    current_tool = {}

    # 1. contentBlockStart - tool use starts
    chunk_start = {
        "contentBlockStart": {
            "start": {
                "toolUse": {
                    "toolUseId": "tooluse_abc123",
                    "name": "add",
                }
            }
        }
    }
    response1, current_tool = model._parse_provider_response_delta(chunk_start, current_tool)
    assert response1.role == "assistant"
    assert response1.tool_calls == []  # No tool calls emitted yet
    assert current_tool["id"] == "tooluse_abc123"
    assert current_tool["function"]["name"] == "add"
    assert current_tool["function"]["arguments"] == ""

    # 2. contentBlockDelta - tool input in single chunk
    chunk_delta = {"contentBlockDelta": {"delta": {"toolUse": {"input": '{"x": 2, "y": 5}'}}}}
    response2, current_tool = model._parse_provider_response_delta(chunk_delta, current_tool)
    assert response2.tool_calls == []  # Still building
    assert current_tool["function"]["arguments"] == '{"x": 2, "y": 5}'

    # 3. contentBlockStop - tool complete
    chunk_stop = {"contentBlockStop": {}}
    response3, current_tool = model._parse_provider_response_delta(chunk_stop, current_tool)
    assert response3.tool_calls is not None
    assert len(response3.tool_calls) == 1
    assert response3.tool_calls[0]["id"] == "tooluse_abc123"
    assert response3.tool_calls[0]["function"]["name"] == "add"
    assert response3.tool_calls[0]["function"]["arguments"] == '{"x": 2, "y": 5}'
    assert response3.extra == {"tool_ids": ["tooluse_abc123"]}
    assert current_tool == {}  # Reset for next tool


def test_parse_streaming_tool_call_with_multiple_chunks():
    """Test parsing a tool call where arguments are split across multiple chunks.

    This tests the bug fix where tool arguments were not being accumulated.
    """
    model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0")

    current_tool = {}

    # 1. contentBlockStart
    chunk_start = {
        "contentBlockStart": {
            "start": {
                "toolUse": {
                    "toolUseId": "tooluse_xyz789",
                    "name": "calculate",
                }
            }
        }
    }
    response1, current_tool = model._parse_provider_response_delta(chunk_start, current_tool)
    assert current_tool["function"]["arguments"] == ""

    # 2. First contentBlockDelta - partial JSON
    chunk_delta1 = {"contentBlockDelta": {"delta": {"toolUse": {"input": '{"op": "mult'}}}}
    response2, current_tool = model._parse_provider_response_delta(chunk_delta1, current_tool)
    assert current_tool["function"]["arguments"] == '{"op": "mult'

    # 3. Second contentBlockDelta - more JSON
    chunk_delta2 = {"contentBlockDelta": {"delta": {"toolUse": {"input": 'iply", "values"'}}}}
    response3, current_tool = model._parse_provider_response_delta(chunk_delta2, current_tool)
    assert current_tool["function"]["arguments"] == '{"op": "multiply", "values"'

    # 4. Third contentBlockDelta - final JSON
    chunk_delta3 = {"contentBlockDelta": {"delta": {"toolUse": {"input": ": [3, 7]}"}}}}
    response4, current_tool = model._parse_provider_response_delta(chunk_delta3, current_tool)
    assert current_tool["function"]["arguments"] == '{"op": "multiply", "values": [3, 7]}'

    # 5. contentBlockStop - tool complete
    chunk_stop = {"contentBlockStop": {}}
    response5, current_tool = model._parse_provider_response_delta(chunk_stop, current_tool)
    assert response5.tool_calls is not None
    assert len(response5.tool_calls) == 1
    assert response5.tool_calls[0]["function"]["arguments"] == '{"op": "multiply", "values": [3, 7]}'
    assert response5.extra == {"tool_ids": ["tooluse_xyz789"]}


def test_parse_streaming_text_content():
    """Test parsing text content deltas (non-tool response)."""
    model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0")

    current_tool = {}

    # Text content delta
    chunk_text = {"contentBlockDelta": {"delta": {"text": "Hello, "}}}
    response1, current_tool = model._parse_provider_response_delta(chunk_text, current_tool)
    assert response1.content == "Hello, "
    assert response1.tool_calls == []
    assert current_tool == {}

    # More text
    chunk_text2 = {"contentBlockDelta": {"delta": {"text": "world!"}}}
    response2, current_tool = model._parse_provider_response_delta(chunk_text2, current_tool)
    assert response2.content == "world!"


def test_parse_streaming_usage_metrics():
    """Test parsing usage metrics from streaming response."""
    model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0")

    current_tool = {}

    # Metadata with usage
    chunk_metadata = {
        "metadata": {
            "usage": {
                "inputTokens": 100,
                "outputTokens": 50,
            }
        }
    }
    response, current_tool = model._parse_provider_response_delta(chunk_metadata, current_tool)
    assert response.response_usage is not None
    assert response.response_usage.input_tokens == 100
    assert response.response_usage.output_tokens == 50
    assert response.response_usage.total_tokens == 150


def test_parse_streaming_empty_tool_input():
    """Test parsing a tool call with empty/no input."""
    model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0")

    current_tool = {}

    # Start tool
    chunk_start = {
        "contentBlockStart": {
            "start": {
                "toolUse": {
                    "toolUseId": "tooluse_empty",
                    "name": "get_weather",
                }
            }
        }
    }
    response1, current_tool = model._parse_provider_response_delta(chunk_start, current_tool)
    assert current_tool["function"]["arguments"] == ""

    # contentBlockDelta with empty input
    chunk_delta = {"contentBlockDelta": {"delta": {"toolUse": {"input": ""}}}}
    response2, current_tool = model._parse_provider_response_delta(chunk_delta, current_tool)
    assert current_tool["function"]["arguments"] == ""

    # Complete tool
    chunk_stop = {"contentBlockStop": {}}
    response3, current_tool = model._parse_provider_response_delta(chunk_stop, current_tool)
    assert response3.tool_calls is not None
    assert response3.tool_calls[0]["function"]["arguments"] == ""


def test_parse_streaming_multiple_sequential_tools():
    """Test parsing multiple tool calls that come sequentially in the stream."""
    model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0")

    current_tool = {}

    # First tool
    chunk_start1 = {
        "contentBlockStart": {
            "start": {
                "toolUse": {
                    "toolUseId": "tool_1",
                    "name": "function_a",
                }
            }
        }
    }
    response1, current_tool = model._parse_provider_response_delta(chunk_start1, current_tool)
    assert current_tool["id"] == "tool_1"

    chunk_delta1 = {"contentBlockDelta": {"delta": {"toolUse": {"input": '{"arg": 1}'}}}}
    response2, current_tool = model._parse_provider_response_delta(chunk_delta1, current_tool)

    chunk_stop1 = {"contentBlockStop": {}}
    response3, current_tool = model._parse_provider_response_delta(chunk_stop1, current_tool)
    assert response3.tool_calls[0]["id"] == "tool_1"
    assert current_tool == {}  # Reset

    # Second tool
    chunk_start2 = {
        "contentBlockStart": {
            "start": {
                "toolUse": {
                    "toolUseId": "tool_2",
                    "name": "function_b",
                }
            }
        }
    }
    response4, current_tool = model._parse_provider_response_delta(chunk_start2, current_tool)
    assert current_tool["id"] == "tool_2"

    chunk_delta2 = {"contentBlockDelta": {"delta": {"toolUse": {"input": '{"arg": 2}'}}}}
    response5, current_tool = model._parse_provider_response_delta(chunk_delta2, current_tool)

    chunk_stop2 = {"contentBlockStop": {}}
    response6, current_tool = model._parse_provider_response_delta(chunk_stop2, current_tool)
    assert response6.tool_calls[0]["id"] == "tool_2"
    assert current_tool == {}


def test_invoke_stream_maintains_tool_state():
    """Test that invoke_stream properly maintains current_tool state across chunks.

    This is a more integrated test that verifies the current_tool dict is passed
    correctly through the streaming loop.
    """
    model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0")

    # Create sample streaming chunks
    chunks = [
        {
            "contentBlockStart": {
                "start": {
                    "toolUse": {
                        "toolUseId": "test_tool",
                        "name": "test_function",
                    }
                }
            }
        },
        {"contentBlockDelta": {"delta": {"toolUse": {"input": '{"param":'}}}},
        {"contentBlockDelta": {"delta": {"toolUse": {"input": ' "value"}'}}}},
        {"contentBlockStop": {}},
    ]

    # Simulate what happens in invoke_stream
    current_tool = {}
    responses = []

    for chunk in chunks:
        model_response, current_tool = model._parse_provider_response_delta(chunk, current_tool)
        responses.append(model_response)

    # Verify the final response has the complete tool call
    final_response = responses[-1]
    assert final_response.tool_calls is not None
    assert len(final_response.tool_calls) == 1
    assert final_response.tool_calls[0]["function"]["arguments"] == '{"param": "value"}'
    assert final_response.extra == {"tool_ids": ["test_tool"]}
