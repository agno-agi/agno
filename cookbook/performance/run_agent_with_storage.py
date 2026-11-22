"""
Storage Run Overhead Benchmark
==============================

Measures Agent.run() / Agent.arun() with an in-memory database and session
history enabled, using an in-process mock model. The difference against the
plain run benchmark is the cost of session persistence: reading the session,
adding history to context and writing the run back to storage.

Each iteration runs against a fresh empty database, so per-iteration work is
constant: InMemoryDb looks sessions up with a linear scan, and a database
that grew across iterations would make later iterations measurably slower
(and would let the sync pass contaminate the async pass). Constructing the
empty InMemoryDb costs about 2.5 us, under 1 percent of the measured run.
"""

from _bench import MockModel, ensure_completed, iterations, run_benchmarks
from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.eval.performance import PerformanceEval

# ---------------------------------------------------------------------------
# Setup: the agent is created once and reused; each iteration is one run
# ---------------------------------------------------------------------------
agent = Agent(
    model=MockModel(),
    db=InMemoryDb(),
    add_history_to_context=True,
    system_message="Be concise, reply with one sentence.",
    telemetry=False,
)


# ---------------------------------------------------------------------------
# Benchmark Functions
# ---------------------------------------------------------------------------
def run_agent_with_storage():
    agent.db = InMemoryDb()
    return ensure_completed(
        agent.run("What is the capital of France?", session_id="bench-session"),
        expected_content="ok",
    )


async def arun_agent_with_storage():
    agent.db = InMemoryDb()
    return ensure_completed(
        await agent.arun("What is the capital of France?", session_id="bench-session"),
        expected_content="ok",
    )


# ---------------------------------------------------------------------------
# Create Evaluations
# ---------------------------------------------------------------------------
run_agent_with_storage_perf = PerformanceEval(
    name="run_agent_with_storage",
    func=run_agent_with_storage,
    num_iterations=iterations(500),
    telemetry=False,
)

arun_agent_with_storage_perf = PerformanceEval(
    name="arun_agent_with_storage",
    func=arun_agent_with_storage,
    num_iterations=iterations(500),
    telemetry=False,
)

# ---------------------------------------------------------------------------
# Run Evaluations
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_benchmarks(
        [run_agent_with_storage_perf, arun_agent_with_storage_perf], group="run"
    )
