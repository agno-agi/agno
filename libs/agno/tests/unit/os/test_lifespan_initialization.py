"""Unit tests for AgentOS lifespan-based initialization."""

import time

from agno.agent.agent import Agent
from agno.os import AgentOS
from agno.team.team import Team
from agno.workflow.workflow import Workflow


def test_os_instantiation_time():
    """AgentOS instantiation should be fast (< 50ms) since heavy init is deferred to lifespan."""
    agents = [Agent(name=f"Agent{i}", telemetry=False) for i in range(5)]
    teams = [Team(name=f"Team{i}", members=[Agent(name=f"TeamAgent{i}", telemetry=False)]) for i in range(3)]
    workflows = [Workflow(name=f"Workflow{i}") for i in range(3)]

    start = time.perf_counter()
    AgentOS(agents=agents, teams=teams, workflows=workflows, telemetry=False)  # type: ignore
    elapsed_ms = (time.perf_counter() - start) * 1000

    # Instantiation should be very fast since heavy work is deferred
    # 50ms is a generous upper bound - actual time should be < 5ms
    assert elapsed_ms < 50, f"AgentOS instantiation took {elapsed_ms:.2f}ms, expected < 50ms"
