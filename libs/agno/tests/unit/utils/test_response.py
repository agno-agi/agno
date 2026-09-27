import pytest

from agno.models.response import ToolExecution
from agno.run.agent import RunPausedEvent
from agno.utils.response import create_paused_run_output_panel, format_tool_calls


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
