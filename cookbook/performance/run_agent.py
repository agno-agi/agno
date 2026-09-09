"""
Agent Run Overhead Benchmark
============================

Measures the full Agent.run() / Agent.arun() loop with an in-process mock
model, so the number is pure framework overhead per run: message building,
system prompt assembly, model invocation plumbing, response parsing, run
output construction and session bookkeeping. No network calls are made.
"""

from _bench import MockModel, ensure_completed, iterations, run_benchmarks
from agno.agent import Agent
from agno.eval.performance import PerformanceEval

# ---------------------------------------------------------------------------
# Setup: the agent is created once and reused; each iteration is one run
# ---------------------------------------------------------------------------
agent = Agent(
    model=MockModel(),
    system_message="Be concise, reply with one sentence.",
    telemetry=False,
)


# ---------------------------------------------------------------------------
# Benchmark Functions
# ---------------------------------------------------------------------------
def run_agent():
    return ensure_completed(
        agent.run("What is the capital of France?"), expected_content="ok"
    )


async def arun_agent():
    return ensure_completed(
        await agent.arun("What is the capital of France?"), expected_content="ok"
    )


# ---------------------------------------------------------------------------
# Create Evaluations
# ---------------------------------------------------------------------------
run_agent_perf = PerformanceEval(
    name="run_agent",
    func=run_agent,
    num_iterations=iterations(500),
    telemetry=False,
)

arun_agent_perf = PerformanceEval(
    name="arun_agent",
    func=arun_agent,
    num_iterations=iterations(500),
    telemetry=False,
)

# ---------------------------------------------------------------------------
# Run Evaluations
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_benchmarks([run_agent_perf, arun_agent_perf], group="run")
