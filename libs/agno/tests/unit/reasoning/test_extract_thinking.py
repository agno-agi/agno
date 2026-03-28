"""Tests for extract_thinking_content in agno.utils.reasoning."""

from agno.utils.reasoning import extract_thinking_content


def test_no_think_tags_returns_none():
    content = "Just a regular response with no thinking."
    reasoning, output = extract_thinking_content(content)
    assert reasoning is None
    assert output == content


def test_empty_string():
    reasoning, output = extract_thinking_content("")
    assert reasoning is None
    assert output == ""


def test_single_think_block():
    content = "<think>Let me reason about this.</think>The answer is 42."
    reasoning, output = extract_thinking_content(content)
    assert reasoning == "Let me reason about this."
    assert output == "The answer is 42."


def test_think_block_with_newlines():
    content = "<think>\nStep 1: analyze\nStep 2: solve\n</think>\nHere is the result."
    reasoning, output = extract_thinking_content(content)
    assert reasoning == "Step 1: analyze\nStep 2: solve"
    assert output == "Here is the result."


def test_multiple_think_blocks():
    content = (
        "<think>First round of thinking.</think>"
        "Intermediate response. "
        "<think>Second round after tool call.</think>"
        "Final answer."
    )
    reasoning, output = extract_thinking_content(content)
    assert "First round of thinking." in reasoning
    assert "Second round after tool call." in reasoning
    assert "Intermediate response." in output
    assert "Final answer." in output
    assert "<think>" not in output
    assert "</think>" not in output


def test_three_think_blocks():
    content = "<think>Block 1</think>Response 1. <think>Block 2</think>Response 2. <think>Block 3</think>Response 3."
    reasoning, output = extract_thinking_content(content)
    assert "Block 1" in reasoning
    assert "Block 2" in reasoning
    assert "Block 3" in reasoning
    assert "<think>" not in output


def test_missing_open_tag():
    content = "Some leaked thinking</think>Actual response."
    reasoning, output = extract_thinking_content(content)
    assert reasoning == "Some leaked thinking"
    assert output == "Actual response."


def test_empty_think_block():
    content = "<think></think>Response only."
    reasoning, output = extract_thinking_content(content)
    # Empty block should not contribute reasoning
    assert output == "Response only."


def test_think_block_only_no_output():
    content = "<think>Only reasoning, no visible response.</think>"
    reasoning, output = extract_thinking_content(content)
    assert reasoning == "Only reasoning, no visible response."
    assert output == ""


def test_whitespace_around_tags():
    content = "  <think>  padded reasoning  </think>  padded output  "
    reasoning, output = extract_thinking_content(content)
    assert reasoning == "padded reasoning"
    assert "padded output" in output
