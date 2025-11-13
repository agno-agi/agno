"""
Unit tests for agno.os.utils functions.

Tests the stringify_input_content and get_run_input utility functions.
"""

import json

import pytest

from agno.models.message import Message
from agno.os.utils import get_run_input, stringify_input_content


def test_stringify_string_input():
    """Test that string inputs are returned as-is."""
    input_str = "generate an image of dog flying"
    result = stringify_input_content(input_str)
    assert result == input_str
    assert isinstance(result, str)


def test_stringify_message_object_input():
    """Test that Message objects are serialized correctly."""
    msg = Message(role="user", content="Hello, world!")
    result = stringify_input_content(msg)

    # Should be valid JSON
    parsed = json.loads(result)
    assert parsed["role"] == "user"
    assert parsed["content"] == "Hello, world!"


def test_stringify_dict_input():
    """Test that dict inputs are serialized to JSON."""
    input_dict = {"key": "value", "number": 42, "nested": {"data": "here"}}
    result = stringify_input_content(input_dict)

    # Should be valid JSON
    parsed = json.loads(result)
    assert parsed["key"] == "value"
    assert parsed["number"] == 42
    assert parsed["nested"]["data"] == "here"


def test_stringify_list_of_message_objects():
    """Test that lists of Message objects are serialized correctly."""
    messages = [
        Message(role="user", content="First message"),
        Message(role="assistant", content="Second message"),
    ]
    result = stringify_input_content(messages)

    # Should be valid JSON
    parsed = json.loads(result)
    assert len(parsed) == 2
    assert parsed[0]["role"] == "user"
    assert parsed[0]["content"] == "First message"
    assert parsed[1]["role"] == "assistant"
    assert parsed[1]["content"] == "Second message"


def test_stringify_list_of_message_dicts_user_first():
    """Test that lists of message dicts return the first user message content."""
    messages = [
        {"role": "user", "content": "User query here"},
        {"role": "assistant", "content": "Assistant response"},
    ]
    result = stringify_input_content(messages)

    # Should return the first user message content
    assert result == "User query here"


def test_stringify_list_of_message_dicts_no_user():
    """Test that lists of non-user message dicts are stringified."""
    messages = [
        {"role": "system", "content": "System message"},
        {"role": "assistant", "content": "Assistant response"},
    ]
    result = stringify_input_content(messages)

    # Should return string representation
    assert isinstance(result, str)


def test_stringify_empty_list():
    """Test that empty lists are handled."""
    result = stringify_input_content([])
    assert result == "[]"


def test_stringify_other_types():
    """Test that other types are stringified."""
    assert stringify_input_content(123) == "123"
    assert stringify_input_content(45.67) == "45.67"
    assert stringify_input_content(True) == "True"
    assert stringify_input_content(None) == "None"


# Tests for get_run_input


def test_get_run_input_agent_with_string():
    """Test extracting input from agent run with string input_content."""
    run_dict = {
        "run_id": "test-run-1",
        "input": {
            "input_content": "generate an image of dog flying",
            "images": [],
        },
        "messages": [
            {"role": "user", "content": "generate an image of dog flying"},
            {"role": "assistant", "content": "Creating image..."},
            {"role": "user", "content": "Take note of the following content"},
        ],
    }

    result = get_run_input(run_dict, is_workflow_run=False)
    assert result == "generate an image of dog flying"


def test_get_run_input_agent_with_message_dict():
    """Test extracting input from agent run with Message dict input_content."""
    run_dict = {
        "run_id": "test-run-2",
        "input": {
            "input_content": {"role": "user", "content": "What is the weather?"},
        },
        "messages": [
            {"role": "user", "content": "What is the weather?"},
        ],
    }

    result = get_run_input(run_dict, is_workflow_run=False)
    parsed = json.loads(result)
    assert parsed["role"] == "user"
    assert parsed["content"] == "What is the weather?"


def test_get_run_input_agent_with_list_of_messages():
    """Test extracting input from agent run with list of messages."""
    run_dict = {
        "run_id": "test-run-3",
        "input": {
            "input_content": [
                {"role": "user", "content": "First query"},
                {"role": "assistant", "content": "First response"},
            ],
        },
    }

    result = get_run_input(run_dict, is_workflow_run=False)
    assert result == "First query"


def test_get_run_input_ignores_synthetic_messages():
    """Test that synthetic 'Take note of the following content' messages are ignored."""
    run_dict = {
        "run_id": "test-run-4",
        "input": {
            "input_content": "create an image of a cat",
        },
        "messages": [
            {"role": "user", "content": "create an image of a cat"},
            {"role": "assistant", "tool_calls": [{"function": "create_image"}]},
            {"role": "tool", "content": "Image created"},
            {"role": "user", "content": "Take note of the following content"},
            {"role": "assistant", "content": "Image shows a cat"},
        ],
    }

    result = get_run_input(run_dict, is_workflow_run=False)
    # Should get the original input, not the synthetic message
    assert result == "create an image of a cat"


def test_get_run_input_team_with_input():
    """Test extracting input from team run."""
    run_dict = {
        "run_id": "test-team-run-1",
        "team_id": "my-team",
        "input": {
            "input_content": "Research the latest AI trends",
        },
    }

    result = get_run_input(run_dict, is_workflow_run=False)
    assert result == "Research the latest AI trends"


def test_get_run_input_workflow_with_string():
    """Test extracting input from workflow run with direct string input."""
    run_dict = {
        "run_id": "test-workflow-run-1",
        "workflow_id": "my-workflow",
        "input": "Process this data",
    }

    result = get_run_input(run_dict, is_workflow_run=True)
    assert result == "Process this data"


def test_get_run_input_workflow_with_dict():
    """Test extracting input from workflow run with dict input."""
    run_dict = {
        "run_id": "test-workflow-run-2",
        "workflow_id": "my-workflow",
        "input": {"query": "test query", "params": {"limit": 10}},
    }

    result = get_run_input(run_dict, is_workflow_run=True)
    # Should stringify the dict
    assert "query" in result
    assert "test query" in result


def test_get_run_input_workflow_with_step_executor_runs():
    """Test extracting input from workflow run via step executor runs."""
    run_dict = {
        "run_id": "test-workflow-run-3",
        "workflow_id": "my-workflow",
        "step_executor_runs": [
            {
                "messages": [
                    {"role": "system", "content": "System message"},
                    {"role": "user", "content": "Step input query"},
                    {"role": "assistant", "content": "Step output"},
                ]
            }
        ],
    }

    result = get_run_input(run_dict, is_workflow_run=True)
    assert result == "Step input query"


def test_get_run_input_fallback_to_messages():
    """Test fallback to scanning messages for backward compatibility."""
    run_dict = {
        "run_id": "test-old-run",
        "messages": [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Old run input"},
            {"role": "assistant", "content": "Old run output"},
        ],
    }

    result = get_run_input(run_dict, is_workflow_run=False)
    assert result == "Old run input"


def test_get_run_input_empty_dict():
    """Test handling of empty run dict."""
    result = get_run_input({}, is_workflow_run=False)
    assert result == ""


def test_get_run_input_without_input_or_messages():
    """Test handling of run dict without input or messages."""
    run_dict = {
        "run_id": "test-run-no-input",
        "status": "completed",
    }

    result = get_run_input(run_dict, is_workflow_run=False)
    assert result == ""


def test_get_run_input_with_none_input_content():
    """Test handling of run with input but None input_content."""
    run_dict = {
        "run_id": "test-run-none",
        "input": {
            "input_content": None,
        },
    }

    result = get_run_input(run_dict, is_workflow_run=False)
    assert result == ""


def test_get_run_input_with_basemodel_dict():
    """Test extracting input from agent run with BaseModel-like dict input_content."""
    run_dict = {
        "run_id": "test-run-model",
        "input": {
            "input_content": {
                "name": "Test User",
                "age": 25,
                "active": True,
            }
        },
    }

    result = get_run_input(run_dict, is_workflow_run=False)
    # Should be JSON string
    parsed = json.loads(result)
    assert parsed["name"] == "Test User"
    assert parsed["age"] == 25


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
