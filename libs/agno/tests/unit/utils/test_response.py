from itertools import permutations

import pytest

from agno.models.response import ToolExecution
from agno.run.agent import RunOutput, RunPausedEvent
from agno.utils.response import create_paused_run_output_panel, format_tool_calls, get_paused_content


def _paused_panel_text(tool_call: ToolExecution) -> str:
    panel = create_paused_run_output_panel(RunPausedEvent(tools=[tool_call]))
    assert panel is not None
    return panel.renderable.plain


@pytest.mark.parametrize(
    "hitl_field",
    ["requires_confirmation", "requires_user_input", "external_execution_required"],
)
@pytest.mark.parametrize(
    "tool_args,expected_args_str",
    [
        # Trailing comma inside a value: rstrip(", ") strips a *set* of chars, so
        # it ate the value's own trailing comma along with the separator.
        ({"cmd": "rm -rf /tmp,"}, "cmd=rm -rf /tmp,"),
        ({"q": "a, b, c,"}, "q=a, b, c,"),
        # A value that is nothing but separator chars was erased entirely.
        ({"s": ","}, "s=,"),
        ({"s": " "}, "s= "),
        # Values that never triggered the bug, kept so the fix can't regress them.
        ({"path": "/tmp/a", "n": 1}, "path=/tmp/a, n=1"),
        ({"items": [1, 2]}, "items=[1, 2]"),
        ({}, ""),
        (None, ""),
    ],
)
def test_paused_panel_preserves_trailing_separator_chars_in_arg_values(
    hitl_field: str, tool_args, expected_args_str: str
):
    """Argument values must be rendered verbatim in the paused-run panel.

    Regression test: the panel accumulated "arg=value, " per argument and then
    called args_str.rstrip(", ") to drop the final separator. rstrip takes a set
    of characters, not a suffix, so it also stripped commas and spaces belonging
    to the last argument's own value. A user confirming `shell(cmd="rm -rf /tmp,")`
    was shown `cmd=rm -rf /tmp` instead -- the panel is the HITL approval surface,
    so it has to show what will actually run.
    """
    tool_call = ToolExecution(tool_name="shell", tool_args=tool_args, **{hitl_field: True})

    assert f"• shell({expected_args_str})\n" in _paused_panel_text(tool_call)


def test_paused_panel_matches_format_tool_calls_arg_rendering():
    """The paused panel and format_tool_calls must agree on how args are rendered.

    format_tool_calls already used ", ".join(...) and was therefore correct; the
    paused panel is now built the same way, so the two cannot drift apart again.
    """
    tool_args = {"cmd": "echo a,", "n": 0}
    tool_call = ToolExecution(tool_name="shell", tool_args=tool_args, requires_confirmation=True)

    assert format_tool_calls([tool_call]) == ["shell(cmd=echo a,, n=0)"]
    assert "• shell(cmd=echo a,, n=0)\n" in _paused_panel_text(tool_call)


@pytest.mark.parametrize(
    "fields,expected",
    [
        (("requires_confirmation", "requires_user_input"), "confirmation or user input"),
        (("requires_confirmation", "external_execution_required"), "confirmation or external execution"),
        (("requires_user_input", "external_execution_required"), "user input or external execution"),
        (
            ("requires_confirmation", "requires_user_input", "external_execution_required"),
            "confirmation, user input, or external execution",
        ),
    ],
)
def test_paused_content_includes_all_tool_requirements_regardless_of_order(fields, expected):
    for ordered_fields in permutations(fields):
        tools = [ToolExecution(**{field: True}) for field in ordered_fields]

        assert get_paused_content(RunOutput(tools=tools)) == f"I have tools to execute, but I need {expected}."


@pytest.mark.parametrize(
    "field,expected",
    [
        ("requires_confirmation", "I have tools to execute, but I need confirmation."),
        ("requires_user_input", "I have tools to execute, but I need user input."),
        ("external_execution_required", "I have tools to execute, but it needs external execution."),
    ],
)
def test_paused_content_preserves_single_requirement_messages(field, expected):
    assert get_paused_content(RunOutput(tools=[ToolExecution(**{field: True})])) == expected


@pytest.mark.parametrize(
    "tools",
    [
        None,
        [],
        [ToolExecution()],
        [ToolExecution(requires_confirmation=True, confirmed=True)],
        [ToolExecution(external_execution_required=True, external_execution_silent=True)],
    ],
)
def test_paused_content_without_visible_pending_requirements_is_empty(tools):
    assert get_paused_content(RunOutput(tools=tools)) == ""


@pytest.mark.parametrize("reverse", [False, True])
def test_paused_content_ignores_silent_and_confirmed_tools(reverse):
    tools = [
        ToolExecution(requires_user_input=True),
        ToolExecution(requires_confirmation=True, confirmed=True),
        ToolExecution(external_execution_required=True, external_execution_silent=True),
    ]
    if reverse:
        tools.reverse()

    assert get_paused_content(RunOutput(tools=tools)) == "I have tools to execute, but I need user input."
