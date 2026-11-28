"""Super Agent runs a component it built in the conversation when a later message is input for it."""

from agno.os.manager.prompts import BUILDER_INSTRUCTIONS, MANAGER_INSTRUCTIONS


def test_super_agent_is_told_to_run_what_it_built_on_input_sent_for_it():
    said = " ".join(MANAGER_INSTRUCTIONS.split())
    # The list of components is in the system message, which a continued conversation is not sent
    # again: a component built in the conversation is known from the earlier turns.
    assert "sends input for a component published in this conversation without asking for a different run" in said
    assert "run that component with the run tools, even for a short answer" in said
    assert 'in your earlier turns even if it is missing from "Components you can run"' in said
    assert "If the earlier build is still a draft, leave it for review." in said
    assert "Do not call a run tool for it." in said
    assert 'When the run tool returns a result, start your reply with "From <component name>"' in said
    assert "For other requests, answer directly when you can finish in a few lines." in said


def test_a_build_still_runs_an_agent_only_when_asked():
    said = " ".join(MANAGER_INSTRUCTIONS.split())
    assert "ask it to run an agent or team only when the person asked for a run" in said
    assert "Run an agent or a team only if asked." in " ".join(BUILDER_INSTRUCTIONS.split())
