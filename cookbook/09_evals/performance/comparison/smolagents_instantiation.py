"""
Smolagents Instantiation Performance Evaluation
===============================================

Demonstrates agent instantiation benchmarking with Smolagents.
"""

from agno.eval.performance import PerformanceEval
from smolagents import InferenceClientModel, Tool, ToolCallingAgent


# ---------------------------------------------------------------------------
# Create Benchmark Tool
# ---------------------------------------------------------------------------
class WeatherTool(Tool):
    name = "weather_tool"
    description = """
    This is a tool that tells the weather"""
    inputs = {
        "city": {
            "type": "string",
            "description": "The city to look up",
        }
    }
    output_type = "string"

    def forward(self, city: str):
        """Use this to get weather information."""
        if city == "nyc":
            return "It might be cloudy in nyc"
        elif city == "sf":
            return "It's always sunny in sf"
        else:
            raise AssertionError("Unknown city")


# ---------------------------------------------------------------------------
# Create Benchmark Function
# ---------------------------------------------------------------------------
def instantiate_agent():
    return ToolCallingAgent(
        tools=[WeatherTool()],
        model=InferenceClientModel(model_id="meta-llama/Llama-3.3-70B-Instruct"),
    )


# ---------------------------------------------------------------------------
# Create Evaluation
# ---------------------------------------------------------------------------
smolagents_instantiation = PerformanceEval(func=instantiate_agent, num_iterations=1000)

# ---------------------------------------------------------------------------
# Run Evaluation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    smolagents_instantiation.run(print_results=True, print_summary=True)
