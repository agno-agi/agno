"""
Workflow Instantiation Benchmark
================================

Measures the cost of creating a two-step Workflow whose steps wrap a
shared Agent. The agent is created once outside the loop; the
measurement is the workflow and step construction itself.
"""

from _bench import iterations, run_benchmarks
from agno.agent import Agent
from agno.eval.performance import PerformanceEval
from agno.workflow import Step, Workflow

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
step_agent = Agent(name="step-agent", telemetry=False)


# ---------------------------------------------------------------------------
# Benchmark Function
# ---------------------------------------------------------------------------
def instantiate_workflow():
    return Workflow(
        name="benchmark-workflow",
        steps=[
            Step(name="research", agent=step_agent),
            Step(name="write", agent=step_agent),
        ],
        telemetry=False,
    )


# ---------------------------------------------------------------------------
# Create Evaluation
# ---------------------------------------------------------------------------
instantiate_workflow_perf = PerformanceEval(
    name="instantiate_workflow",
    func=instantiate_workflow,
    num_iterations=iterations(1000),
    telemetry=False,
)

# ---------------------------------------------------------------------------
# Run Evaluation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_benchmarks([instantiate_workflow_perf], group="instantiation")
