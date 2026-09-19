"""
Streaming Run Overhead Benchmark
================================

Measures Agent.run(stream=True) / Agent.arun(stream=True) with an
in-process mock model, draining the full event stream. Compares the cost
of the streaming event machinery against the plain run loop.
"""

from _bench import MockModel, iterations, run_benchmarks
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
def _verify_events(events):
    if not events:
        raise RuntimeError("Streaming run yielded no events")
    for event in events:
        if "Error" in type(event).__name__:
            raise RuntimeError(
                "Streaming run produced an error event: " + type(event).__name__
            )
    if not any(getattr(event, "content", None) for event in events):
        raise RuntimeError("Streaming run produced no content event")
    return events


def run_agent_streaming():
    return _verify_events(
        list(agent.run("What is the capital of France?", stream=True))
    )


async def arun_agent_streaming():
    events = []
    async for event in agent.arun("What is the capital of France?", stream=True):
        events.append(event)
    return _verify_events(events)


# ---------------------------------------------------------------------------
# Create Evaluations
# ---------------------------------------------------------------------------
run_agent_streaming_perf = PerformanceEval(
    name="run_agent_streaming",
    func=run_agent_streaming,
    num_iterations=iterations(500),
    telemetry=False,
)

arun_agent_streaming_perf = PerformanceEval(
    name="arun_agent_streaming",
    func=arun_agent_streaming,
    num_iterations=iterations(500),
    telemetry=False,
)

# ---------------------------------------------------------------------------
# Run Evaluations
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_benchmarks([run_agent_streaming_perf, arun_agent_streaming_perf], group="run")
