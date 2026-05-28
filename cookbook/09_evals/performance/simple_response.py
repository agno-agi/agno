"""
Simple Response Performance Evaluation
======================================

Demonstrates baseline response performance for a single prompt.
"""

from agno.agent import Agent
from agno.eval.performance import PerformanceEval
from agno.models.openai import OpenAIChat


# ---------------------------------------------------------------------------
# Create Benchmark Function
# ---------------------------------------------------------------------------
def run_agent():
    agent = Agent(
        model=OpenAIChat(id="gpt-5.2"),
        system_message="Be concise, reply with one sentence.",
    )

    response = agent.run("What is the capital of France?")
    print(f"Agent response: {response.content}")

    return response


# ---------------------------------------------------------------------------
# Create Evaluation
# ---------------------------------------------------------------------------
simple_response_perf = PerformanceEval(
    name="Simple Performance Evaluation",
    func=run_agent,
    num_iterations=1,
    warmup_runs=0,
)

# ---------------------------------------------------------------------------
# Run Evaluation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    simple_response_perf.run(print_results=True, print_summary=True)
