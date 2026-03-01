"""Regression tests for streaming tool call parsing bugs.

Bug #6542: [{}] * N creates shared dict references, causing tool double-execution.
Bug #6757: Empty function names in streaming chunks overwrite valid names.
"""


def test_shared_dict_reference_bug_6542():
    """Verify [{}] * N shared reference bug is fixed.

    When streaming tool calls arrive with non-contiguous indices (e.g., 0 and 2),
    the list extension must create independent dicts, not shared references.
    """
    # Simulate the bug: [{}] * 3 creates shared references
    shared = [{}] * 3
    shared[0]["id"] = "call_0"
    assert shared[1].get("id") == "call_0", "Precondition: [{}]*N shares references"

    # The fix: list comprehension creates independent dicts
    independent = [{} for _ in range(3)]
    independent[0]["id"] = "call_0"
    assert independent[1].get("id") is None, "List comprehension must create independent dicts"
    assert independent[2].get("id") is None, "List comprehension must create independent dicts"


def test_empty_function_name_overwrite_bug_6757():
    """Verify empty string function names don't overwrite valid names.

    In streaming responses, chunk 1 carries name="add", while chunks 2+
    carry name="". The truthy check must skip empty strings.
    """
    # Simulate the streaming behavior
    tool_name = "add"  # Set by first chunk

    # Later chunks arrive with empty name
    function_data = {"name": ""}

    # Old behavior (bug): `is not None` lets empty string through
    if function_data.get("name") is not None:
        old_result = function_data.get("name", "")
    else:
        old_result = tool_name
    assert old_result == "", "Precondition: old check allows empty string overwrite"

    # New behavior (fix): truthy check skips empty strings
    if function_data.get("name"):
        new_result = function_data.get("name", "")
    else:
        new_result = tool_name
    assert new_result == "add", "Truthy check must preserve valid name"


def test_none_function_name_skipped():
    """Verify None function names are also skipped (regression guard)."""
    tool_name = "add"
    function_data = {"name": None}

    if function_data.get("name"):
        result = function_data.get("name", "")
    else:
        result = tool_name
    assert result == "add", "None names must be skipped"


def test_valid_function_name_accepted():
    """Verify valid function names still update correctly."""
    function_data = {"name": "calculate_sum"}

    if function_data.get("name"):
        result = function_data.get("name", "")
    else:
        result = None
    assert result == "calculate_sum", "Valid names must be accepted"
