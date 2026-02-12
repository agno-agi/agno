"""Tests for multi-round Human-in-the-Loop (HITL) user input flows.

These tests verify that active_requirements is correctly populated across
multiple continue_run() calls when new tools are paused in each round.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.decorator import tool
from agno.tools.user_control_flow import UserControlFlowTools


def test_multi_round_user_input_with_decorator(shared_db):
    """Test multiple rounds of user input with @tool decorator."""
    call_count = 0

    @tool(requires_user_input=True, user_input_fields=["answer"])
    def ask_question(question: str, answer: str = ""):
        nonlocal call_count
        call_count += 1
        return f"Q{call_count}: {question} -> A: {answer}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[ask_question],
        instructions="""You are a survey bot. Ask 3 questions one at a time.
        After each answer, call ask_question again with the next question.
        Questions: 1) What is your name? 2) What is your age? 3) What is your city?
        After all 3 questions, summarize the answers.""",
        db=shared_db,
        telemetry=False,
    )

    session_id = "test_multi_round_decorator"

    # Round 1
    response = agent.run("Start the survey", session_id=session_id)

    assert response.is_paused, "Run should be paused after first tool call"
    assert len(response.active_requirements) == 1, "Should have 1 active requirement"
    assert response.active_requirements[0].needs_user_input

    # Fill in first answer
    response.active_requirements[0].user_input_schema[0].value = "John"  # type: ignore

    # Round 2
    response = agent.continue_run(
        run_id=response.run_id,
        requirements=response.requirements,
        session_id=session_id,
    )

    if response.is_paused:
        # Verify we have a NEW active requirement
        assert len(response.active_requirements) >= 1, "Should have at least 1 active requirement for the new question"
        assert response.active_requirements[0].needs_user_input

        # Fill in second answer
        response.active_requirements[0].user_input_schema[0].value = "25"  # type: ignore

        # Round 3
        response = agent.continue_run(
            run_id=response.run_id,
            requirements=response.requirements,
            session_id=session_id,
        )

        if response.is_paused:
            assert len(response.active_requirements) >= 1
            response.active_requirements[0].user_input_schema[0].value = "NYC"  # type: ignore

            # Final round
            response = agent.continue_run(
                run_id=response.run_id,
                requirements=response.requirements,
                session_id=session_id,
            )

    # Final response should not be paused
    assert not response.is_paused, "Final response should not be paused"


def test_multi_round_user_control_flow_tools(shared_db):
    """Test multiple rounds using UserControlFlowTools (get_user_input).

    This is the exact scenario from the reported bug where active_requirements
    was empty on subsequent continue_run() calls.
    """
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[UserControlFlowTools()],
        instructions="""Ask questions in multiple rounds.
        Round 1: Ask for destination using get_user_input
        Round 2: After getting destination, ask for travel dates using get_user_input
        Round 3: After getting dates, ask for budget using get_user_input
        After all 3 rounds, provide a summary.""",
        db=shared_db,
        telemetry=False,
    )

    session_id = "test_multi_round_user_control"

    # Round 1
    response = agent.run("I want to plan a trip", session_id=session_id)

    assert response.is_paused, "Run should be paused for user input"
    assert len(response.requirements) >= 1, "Should have at least 1 requirement"  # type: ignore
    assert len(response.active_requirements) >= 1, "Should have at least 1 active requirement"

    # Track tool_call_ids to verify new requirements are created
    first_tool_id = response.active_requirements[0].tool_execution.tool_call_id  # type: ignore

    # Fill in first round answers
    for field in response.active_requirements[0].user_input_schema:  # type: ignore
        field.value = f"test_value_for_{field.name}"

    # Round 2
    response = agent.continue_run(
        run_id=response.run_id,
        requirements=response.requirements,
        session_id=session_id,
    )

    round_count = 1
    max_rounds = 5  # Safety limit

    while response.is_paused and round_count < max_rounds:
        round_count += 1

        # THE KEY ASSERTION: active_requirements should NOT be empty
        # when the run is paused with new paused tools
        paused_tools = [t for t in response.tools or [] if t.is_paused]
        if paused_tools:
            assert len(response.active_requirements) >= 1, (
                f"Round {round_count}: active_requirements should not be empty "
                f"when there are {len(paused_tools)} paused tools. "
                f"Total requirements: {len(response.requirements) if response.requirements else 0}"
            )

            # Verify the new requirement has a different tool_call_id
            new_tool_id = response.active_requirements[0].tool_execution.tool_call_id
            assert new_tool_id != first_tool_id, "New requirement should have different tool_call_id"

        # Fill in answers for this round
        for req in response.active_requirements:
            if req.needs_user_input and req.user_input_schema:
                for field in req.user_input_schema:
                    field.value = f"round{round_count}_{field.name}"

        response = agent.continue_run(
            run_id=response.run_id,
            requirements=response.requirements,
            session_id=session_id,
        )

    # Should complete within max_rounds
    assert round_count < max_rounds, f"Test didn't complete within {max_rounds} rounds"


def test_requirements_accumulate_across_rounds(shared_db):
    """Test that requirements list grows with each round, maintaining history."""

    @tool(requires_user_input=True, user_input_fields=["value"])
    def collect_value(field_name: str, value: str = ""):
        return f"{field_name}={value}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[collect_value],
        instructions="""Collect 3 values one at a time:
        1. First call collect_value for 'name'
        2. Then call collect_value for 'age'
        3. Then call collect_value for 'city'
        After collecting all 3, return a summary.""",
        db=shared_db,
        telemetry=False,
    )

    session_id = "test_requirements_accumulate"

    response = agent.run("Collect my info", session_id=session_id)

    requirements_count_history = []
    active_count_history = []

    round_num = 0
    max_rounds = 5

    while response.is_paused and round_num < max_rounds:
        round_num += 1

        requirements_count_history.append(len(response.requirements or []))
        active_count_history.append(len(response.active_requirements))

        # Each round should have at least 1 active requirement
        # Note: The model may batch multiple tool calls in a single response
        assert len(response.active_requirements) >= 1, (
            f"Round {round_num}: Should have at least 1 active requirement, got {len(response.active_requirements)}"
        )

        # Fill the values for all active requirements
        for i, req in enumerate(response.active_requirements):
            if req.user_input_schema:
                for field in req.user_input_schema:
                    if field.value is None:
                        field.value = f"value{round_num}_{i}"

        response = agent.continue_run(
            run_id=response.run_id,
            requirements=response.requirements,
            session_id=session_id,
        )

    # Verify requirements accumulated (each round adds 1)
    if len(requirements_count_history) >= 2:
        for i in range(1, len(requirements_count_history)):
            assert requirements_count_history[i] >= requirements_count_history[i - 1], (
                f"Requirements should accumulate: {requirements_count_history}"
            )

    # Active requirements should always be at least 1 (model may batch calls)
    for count in active_count_history:
        assert count >= 1, f"Active requirements per round should be at least 1: {active_count_history}"
