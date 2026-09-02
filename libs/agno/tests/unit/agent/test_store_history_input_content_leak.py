"""Reproduction tests for the history leak through scrub_history_messages_from_run_output.

A team delegates by passing the member's prior conversation as the member's *input*
(`input=member_agent_task if not history else history` in team/_default_tools.py), so for a
member run the history is stored on `input.input_content` and never reaches
`run_response.messages`. Filtering only `messages` therefore left `store_history_messages=False`
with no effect on the row the member is actually stored in.
"""

import copy

from agno.agent.agent import Agent
from agno.models.message import Message
from agno.run.agent import RunInput, RunOutput
from agno.run.team import TeamRunInput, TeamRunOutput
from agno.utils.agent import scrub_history_messages_from_run_output

SECRET = "MARKER-SECRET-IN-HISTORY"


def _history_message(content: str = SECRET) -> Message:
    message = Message(role="user", content=content)
    message.from_history = True
    return message


def _delegated_input(*, task: str = "summarize the quarter") -> list:
    """The shape team/_default_tools.py builds: history, then the task appended untagged."""
    return [_history_message(), Message(role="user", content=task)]


# -- Core scrub function tests --


def test_scrub_history_drops_history_from_input_content():
    """The member's history must not survive on input.input_content."""
    run_output = RunOutput(input=RunInput(input_content=_delegated_input()))

    scrub_history_messages_from_run_output(run_output)

    contents = [message.content for message in run_output.input.input_content]
    assert SECRET not in contents, "history content should be gone from input_content"


def test_scrub_history_keeps_the_current_task():
    """The task is appended to the history list without from_history; it is input, not history."""
    run_output = RunOutput(input=RunInput(input_content=_delegated_input(task="summarize the quarter")))

    scrub_history_messages_from_run_output(run_output)

    assert len(run_output.input.input_content) == 1
    assert run_output.input.input_content[0].content == "summarize the quarter"


def test_scrub_history_still_filters_messages():
    """The existing messages behaviour is unchanged."""
    run_output = RunOutput(
        messages=[_history_message(), Message(role="user", content="live")],
    )

    scrub_history_messages_from_run_output(run_output)

    assert [message.content for message in run_output.messages] == ["live"]


def test_scrub_history_handles_team_run_output():
    """The same path exists on TeamRunOutput."""
    team_output = TeamRunOutput(input=TeamRunInput(input_content=_delegated_input()))

    scrub_history_messages_from_run_output(team_output)

    contents = [message.content for message in team_output.input.input_content]
    assert SECRET not in contents


# -- Shapes that must be left alone --


def test_scrub_history_leaves_a_string_input_untouched():
    """input_content is usually a plain string; it carries no history entries."""
    run_output = RunOutput(input=RunInput(input_content="just a task"))

    scrub_history_messages_from_run_output(run_output)

    assert run_output.input.input_content == "just a task"


def test_scrub_history_preserves_non_message_list_items():
    """A list of dicts or strings is a legitimate input shape and is not history."""
    run_output = RunOutput(input=RunInput(input_content=[{"role": "user"}, "plain", _history_message()]))

    scrub_history_messages_from_run_output(run_output)

    assert run_output.input.input_content == [{"role": "user"}, "plain"]


def test_scrub_history_handles_a_missing_input():
    """A run with no input must not raise."""
    run_output = RunOutput(input=None)

    scrub_history_messages_from_run_output(run_output)

    assert run_output.input is None


# -- The live run must not be mutated --


def test_scrub_history_does_not_mutate_the_shared_run_input():
    """A shallow storage copy shares its RunInput with the live run.

    Filtering in place would strip the history off a run that is still executing, so the
    RunInput is replaced on the copy instead.
    """
    live_run = RunOutput(input=RunInput(input_content=_delegated_input()))
    original_input = live_run.input

    storage_copy = copy.copy(live_run)
    scrub_history_messages_from_run_output(storage_copy)

    assert storage_copy.input is not original_input, "the copy should get its own RunInput"
    assert len(live_run.input.input_content) == 2, "the live run must keep its history"
    assert live_run.input.input_content[0].content == SECRET


def test_scrub_history_keeps_the_same_run_input_when_nothing_is_filtered():
    """No history means no copy, so the common path allocates nothing."""
    run_output = RunOutput(input=RunInput(input_content=[Message(role="user", content="task")]))
    original_input = run_output.input

    scrub_history_messages_from_run_output(run_output)

    assert run_output.input is original_input


# -- Storage-flag wiring --


def test_scrub_run_output_for_storage_drops_input_history_when_flag_is_off():
    """The delegate path calls this entry point on the member run before upsert_run."""
    from agno.agent._run import scrub_run_output_for_storage

    member_agent = Agent(store_history_messages=False)
    member_run = RunOutput(agent_id=member_agent.id, input=RunInput(input_content=_delegated_input()))

    scrub_run_output_for_storage(member_agent, member_run)

    contents = [message.content for message in member_run.input.input_content]
    assert SECRET not in contents


def test_scrub_run_output_for_storage_keeps_input_history_when_flag_is_on():
    """store_history_messages=True must be untouched by this change."""
    from agno.agent._run import scrub_run_output_for_storage

    member_agent = Agent(store_history_messages=True)
    member_run = RunOutput(agent_id=member_agent.id, input=RunInput(input_content=_delegated_input()))

    scrub_run_output_for_storage(member_agent, member_run)

    contents = [message.content for message in member_run.input.input_content]
    assert SECRET in contents
