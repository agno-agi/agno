"""Reproduction tests for the tool-result leak through scrub_tool_results_from_run_output.

store_tool_messages=False removes tool messages from run_response.messages, but the tool's
return value is stored in two other places in the same session row: run_response.tools[*].result
and requirements[*].tool_execution.result. These tests prove both are blanked.

They also cover the in-place hazard the fix introduces: blanking mutates ToolExecution objects
that a shallow storage copy shares with the live run, so the mid-run checkpoint path has to
isolate them first — the same hazard isolate_media_scrub_targets already handles for media.
"""

from agno.agent.agent import Agent
from agno.models.response import ToolExecution
from agno.run.agent import RunOutput
from agno.run.requirement import RunRequirement
from agno.run.team import TeamRunOutput
from agno.utils.agent import (
    isolate_tool_scrub_targets,
    scrub_tool_results_from_run_output,
)

SECRET = "SSN-000-11-2222-BASELINE"


def _tool_execution(tool_call_id: str = "call_1", **kwargs) -> ToolExecution:
    return ToolExecution(tool_call_id=tool_call_id, tool_name="peek", result=SECRET, **kwargs)


# -- Core scrub function tests --


def test_scrub_tool_results_blanks_stored_tool_result():
    """The tool's return value on run_response.tools must not survive the scrub."""
    run_output = RunOutput(tools=[_tool_execution()])

    scrub_tool_results_from_run_output(run_output)

    assert run_output.tools[0].result is None, "tools[0].result should be None after scrub"


def test_scrub_tool_results_blanks_requirement_tool_result():
    """requirements[*].tool_execution.result is a second copy of the same value."""
    tool_execution = _tool_execution()
    run_output = RunOutput(requirements=[RunRequirement(tool_execution=tool_execution)])

    scrub_tool_results_from_run_output(run_output)

    assert run_output.requirements[0].tool_execution.result is None


def test_scrub_tool_results_blanks_results_with_no_messages():
    """A run with no messages still has to be scrubbed.

    The message-filtering step returns early when messages is empty; the stored results
    must be blanked regardless, or a run whose messages were already stripped keeps its
    tool output.
    """
    run_output = RunOutput(messages=None, tools=[_tool_execution()])

    scrub_tool_results_from_run_output(run_output)

    assert run_output.tools[0].result is None


def test_scrub_tool_results_blanks_team_run_output():
    """The same leak exists on TeamRunOutput."""
    team_output = TeamRunOutput(tools=[_tool_execution()])

    scrub_tool_results_from_run_output(team_output)

    assert team_output.tools[0].result is None


# -- The external-execution carve-out --


def test_scrub_tool_results_keeps_result_an_unresolved_requirement_still_needs():
    """An unresolved requirement's result is load-bearing for resume, so it is kept.

    For external execution the caller's answer arrives as the tool result; blanking it
    would discard the payload continue_run needs to finish the run.
    """
    tool_execution = _tool_execution(external_execution_required=True)
    requirement = RunRequirement(tool_execution=tool_execution)
    assert not requirement.is_resolved()

    run_output = RunOutput(tools=[tool_execution], requirements=[requirement])
    scrub_tool_results_from_run_output(run_output)

    assert run_output.tools[0].result == SECRET
    assert run_output.requirements[0].tool_execution.result == SECRET


def test_scrub_tool_results_blanks_result_once_the_requirement_is_resolved():
    """Once the requirement is resolved the result is a record, not a resume payload."""
    tool_execution = _tool_execution(external_execution_required=True)
    requirement = RunRequirement(tool_execution=tool_execution)
    requirement.external_execution_result = "client answer"
    assert requirement.is_resolved()

    run_output = RunOutput(tools=[tool_execution], requirements=[requirement])
    scrub_tool_results_from_run_output(run_output)

    assert run_output.tools[0].result is None


# -- Storage-flag wiring --


def test_scrub_run_output_for_storage_blanks_result_when_flag_is_off():
    """The agent-level entry point applies it, which is what the DB write path calls."""
    from agno.agent._run import scrub_run_output_for_storage

    agent = Agent(store_tool_messages=False)
    run_output = RunOutput(agent_id=agent.id, tools=[_tool_execution()])

    scrub_run_output_for_storage(agent, run_output)

    assert run_output.tools[0].result is None


def test_scrub_run_output_for_storage_keeps_result_when_flag_is_on():
    """store_tool_messages=True must be untouched by this change."""
    from agno.agent._run import scrub_run_output_for_storage

    agent = Agent(store_tool_messages=True)
    run_output = RunOutput(agent_id=agent.id, tools=[_tool_execution()])

    scrub_run_output_for_storage(agent, run_output)

    assert run_output.tools[0].result == SECRET


# -- In-flight isolation --


def test_isolate_tool_scrub_targets_protects_the_live_run():
    """Scrubbing an isolated storage copy must not blank the live run's results."""
    import copy

    live_run = RunOutput(tools=[_tool_execution()])

    storage_copy = copy.copy(live_run)
    isolate_tool_scrub_targets(storage_copy)
    scrub_tool_results_from_run_output(storage_copy)

    assert storage_copy.tools[0].result is None, "storage copy should be scrubbed"
    assert live_run.tools[0].result == SECRET, "live run must keep its tool result"


def test_isolate_tool_scrub_targets_keeps_tools_and_requirements_aliased():
    """A ToolExecution reached through both tools and a requirement stays one object."""
    import copy

    tool_execution = _tool_execution()
    live_run = RunOutput(tools=[tool_execution], requirements=[RunRequirement(tool_execution=tool_execution)])

    storage_copy = copy.copy(live_run)
    isolate_tool_scrub_targets(storage_copy)

    assert storage_copy.tools[0] is storage_copy.requirements[0].tool_execution
    assert storage_copy.tools[0] is not tool_execution


def test_checkpoint_storage_copy_does_not_strip_the_live_run():
    """The real mid-run checkpoint path, which is where the hazard would bite."""
    from agno.agent._run import _scrub_and_propagate_session_state

    agent = Agent(store_tool_messages=False)
    live_run = RunOutput(agent_id=agent.id, tools=[_tool_execution()])

    storage_copy = _scrub_and_propagate_session_state(agent, live_run, None, isolate_inflight=True)

    assert storage_copy.tools[0].result is None, "the persisted copy should carry no result"
    assert live_run.tools[0].result == SECRET, (
        "the still-running run must keep its tool result; without isolation the checkpoint "
        "strips it in place and the run continues without its own tool output"
    )
