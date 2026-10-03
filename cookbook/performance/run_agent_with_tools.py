"""
Tool Call Run Overhead Benchmark
================================

Measures a full two-turn tool loop with an in-process mock model:
model turn requesting a tool call, real tool execution, second model turn
producing the final answer. The number is the framework's tool dispatch
overhead: schema lookup, argument parsing, function invocation, result
formatting and the extra model round-trip plumbing.
"""

from _bench import (
    MockToolModel,
    add_numbers,
    ensure_completed,
    iterations,
    run_benchmarks,
)
from agno.agent import Agent
from agno.eval.performance import PerformanceEval

# ---------------------------------------------------------------------------
# Setup: the agent is created once and reused; each iteration is one run
# ---------------------------------------------------------------------------
agent = Agent(
    model=MockToolModel(),
    tools=[add_numbers],
    system_message="Use the add_numbers tool.",
    telemetry=False,
)


# ---------------------------------------------------------------------------
# Benchmark Functions
# ---------------------------------------------------------------------------
def run_agent_with_tools():
    return ensure_completed(
        agent.run("Add 1 and 2."), expected_content="done", expect_tool_success=True
    )


async def arun_agent_with_tools():
    return ensure_completed(
        await agent.arun("Add 1 and 2."),
        expected_content="done",
        expect_tool_success=True,
    )


# ---------------------------------------------------------------------------
# Create Evaluations
# ---------------------------------------------------------------------------
run_agent_with_tools_perf = PerformanceEval(
    name="run_agent_with_tools",
    func=run_agent_with_tools,
    num_iterations=iterations(500),
    telemetry=False,
)

arun_agent_with_tools_perf = PerformanceEval(
    name="arun_agent_with_tools",
    func=arun_agent_with_tools,
    num_iterations=iterations(500),
    telemetry=False,
)

# ---------------------------------------------------------------------------
# Run Evaluations
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_benchmarks([run_agent_with_tools_perf, arun_agent_with_tools_perf], group="run")
