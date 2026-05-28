"""
Comprehensive test for stop_reason across all Agent and Team paths.

Tests:
1. Agent sync non-streaming
2. Agent sync streaming
3. Agent async non-streaming
4. Agent async streaming
5. Team sync non-streaming
6. Team sync streaming
"""

import asyncio
from agno.agent import Agent
from agno.team import Team
from agno.models.anthropic import Claude
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput


def test_agent_sync_nonstreaming():
    """Test Agent sync non-streaming stop_reason."""
    print("=" * 60)
    print("1. Agent sync non-streaming")
    print("=" * 60)

    agent = Agent(
        model=Claude(id="claude-sonnet-4-20250514", max_tokens=10),
        markdown=True,
    )

    response = agent.run("Write a detailed essay about climate change.")
    print(f"Content: {response.content[:50]}..." if response.content else "No content")
    print(f"Stop reason: {response.stop_reason}")
    assert response.stop_reason == "max_tokens", f"Expected 'max_tokens', got '{response.stop_reason}'"
    print("PASS")
    print()


def test_agent_sync_streaming():
    """Test Agent sync streaming stop_reason."""
    print("=" * 60)
    print("2. Agent sync streaming")
    print("=" * 60)

    agent = Agent(
        model=Claude(id="claude-sonnet-4-20250514", max_tokens=10),
        markdown=True,
    )

    final_response = None
    for chunk in agent.run("Write a detailed essay about climate change.", stream=True, yield_run_output=True):
        if isinstance(chunk, RunOutput):
            final_response = chunk

    print(f"Content: {final_response.content[:50]}..." if final_response and final_response.content else "No content")
    print(f"Stop reason: {final_response.stop_reason if final_response else None}")
    assert final_response is not None, "No RunOutput received"
    assert final_response.stop_reason == "max_tokens", f"Expected 'max_tokens', got '{final_response.stop_reason}'"
    print("PASS")
    print()


async def test_agent_async_nonstreaming():
    """Test Agent async non-streaming stop_reason."""
    print("=" * 60)
    print("3. Agent async non-streaming")
    print("=" * 60)

    agent = Agent(
        model=Claude(id="claude-sonnet-4-20250514", max_tokens=10),
        markdown=True,
    )

    response = await agent.arun("Write a detailed essay about climate change.")
    print(f"Content: {response.content[:50]}..." if response.content else "No content")
    print(f"Stop reason: {response.stop_reason}")
    assert response.stop_reason == "max_tokens", f"Expected 'max_tokens', got '{response.stop_reason}'"
    print("PASS")
    print()


async def test_agent_async_streaming():
    """Test Agent async streaming stop_reason."""
    print("=" * 60)
    print("4. Agent async streaming")
    print("=" * 60)

    agent = Agent(
        model=Claude(id="claude-sonnet-4-20250514", max_tokens=10),
        markdown=True,
    )

    final_response = None
    async for chunk in agent.arun("Write a detailed essay about climate change.", stream=True, yield_run_output=True):
        if isinstance(chunk, RunOutput):
            final_response = chunk

    print(f"Content: {final_response.content[:50]}..." if final_response and final_response.content else "No content")
    print(f"Stop reason: {final_response.stop_reason if final_response else None}")
    assert final_response is not None, "No RunOutput received"
    assert final_response.stop_reason == "max_tokens", f"Expected 'max_tokens', got '{final_response.stop_reason}'"
    print("PASS")
    print()


def test_team_sync_nonstreaming():
    """Test Team sync non-streaming stop_reason."""
    print("=" * 60)
    print("5. Team sync non-streaming")
    print("=" * 60)

    # Team requires at least one member agent
    member_agent = Agent(
        name="Writer",
        model=Claude(id="claude-sonnet-4-20250514", max_tokens=10),
        markdown=True,
    )

    team = Team(
        name="TestTeam",
        mode="coordinate",
        model=Claude(id="claude-sonnet-4-20250514", max_tokens=10),
        members=[member_agent],
        markdown=True,
    )

    response = team.run("Write a detailed essay about climate change.")
    print(f"Content: {response.content[:50]}..." if response.content else "No content")
    print(f"Stop reason: {response.stop_reason}")
    assert response.stop_reason == "max_tokens", f"Expected 'max_tokens', got '{response.stop_reason}'"
    print("PASS")
    print()


def test_team_sync_streaming():
    """Test Team sync streaming stop_reason."""
    print("=" * 60)
    print("6. Team sync streaming")
    print("=" * 60)

    member_agent = Agent(
        name="Writer",
        model=Claude(id="claude-sonnet-4-20250514", max_tokens=10),
        markdown=True,
    )

    team = Team(
        name="TestTeam",
        mode="coordinate",
        model=Claude(id="claude-sonnet-4-20250514", max_tokens=10),
        members=[member_agent],
        markdown=True,
    )

    final_response = None
    for chunk in team.run("Write a detailed essay about climate change.", stream=True, yield_run_output=True):
        if isinstance(chunk, TeamRunOutput):
            final_response = chunk

    print(f"Content: {final_response.content[:50]}..." if final_response and final_response.content else "No content")
    print(f"Stop reason: {final_response.stop_reason if final_response else None}")
    assert final_response is not None, "No TeamRunOutput received"
    assert final_response.stop_reason == "max_tokens", f"Expected 'max_tokens', got '{final_response.stop_reason}'"
    print("PASS")
    print()


def test_normal_completion():
    """Test normal completion returns end_turn."""
    print("=" * 60)
    print("7. Normal completion (end_turn)")
    print("=" * 60)

    agent = Agent(
        model=Claude(id="claude-sonnet-4-20250514", max_tokens=100),
        markdown=True,
    )

    response = agent.run("Say hello in one word.")
    print(f"Content: {response.content}")
    print(f"Stop reason: {response.stop_reason}")
    assert response.stop_reason == "end_turn", f"Expected 'end_turn', got '{response.stop_reason}'"
    print("PASS")
    print()


async def run_all_tests():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("STOP_REASON COMPREHENSIVE TEST SUITE")
    print("=" * 60 + "\n")

    # Sync tests
    test_agent_sync_nonstreaming()
    test_agent_sync_streaming()

    # Async tests
    await test_agent_async_nonstreaming()
    await test_agent_async_streaming()

    # Team tests
    test_team_sync_nonstreaming()
    test_team_sync_streaming()

    # Normal completion
    test_normal_completion()

    print("=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
