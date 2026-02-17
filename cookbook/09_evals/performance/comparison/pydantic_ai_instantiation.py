"""
PydanticAI Instantiation Performance Evaluation
===============================================

Demonstrates agent instantiation benchmarking with PydanticAI.
"""

from typing import Literal

from agno.eval.performance import PerformanceEval
from pydantic_ai import Agent


# ---------------------------------------------------------------------------
# Create Benchmark Function
# ---------------------------------------------------------------------------
def instantiate_agent():
    agent = Agent("openai:gpt-4o", system_prompt="Be concise, reply with one sentence.")

    # Tool definition remains scoped to agent construction by design.
    @agent.tool_plain
    def get_weather(city: Literal["nyc", "sf"]):
        """Use this to get weather information."""
        if city == "nyc":
            return "It might be cloudy in nyc"
        elif city == "sf":
            return "It's always sunny in sf"
        else:
            raise AssertionError("Unknown city")

    return agent


# ---------------------------------------------------------------------------
# Create Evaluation
# ---------------------------------------------------------------------------
pydantic_instantiation = PerformanceEval(func=instantiate_agent, num_iterations=1000)

# ---------------------------------------------------------------------------
# Run Evaluation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    pydantic_instantiation.run(print_results=True, print_summary=True)
