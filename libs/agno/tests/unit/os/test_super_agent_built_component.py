"""Super Agent runs a component it built in the conversation when a later message is input for it."""

from agno.os.manager.prompts import BUILDER_INSTRUCTIONS, MANAGER_INSTRUCTIONS


def test_super_agent_is_told_to_run_what_it_built_on_input_sent_for_it():
    said = " ".join(MANAGER_INSTRUCTIONS.split())
    # The list of components is in the system message, which a continued conversation is not sent
    # again: a component built in the conversation is known from the earlier turns.
    assert 'named in your earlier turns and may be missing from "Components you can run"' in said
    assert "When a message after the build is plainly input for it" in said
    assert "run it on that message with the run tools, even when you could answer in a few lines yourself" in said
    assert "report what it returned, saying which component it came from" in said
    # Nothing else runs it.
    assert "A message about anything else gets your own answer, and the component is not run." in said


def test_a_build_still_runs_an_agent_only_when_asked():
    said = " ".join(MANAGER_INSTRUCTIONS.split())
    assert "ask it to run an agent or team only when the person asked for a run" in said
    assert "Do not run a component for something you can finish in a few lines." in said
    assert "Run an agent or a team only if asked." in " ".join(BUILDER_INSTRUCTIONS.split())
