"""Run `pip install smolagents` to install dependencies."""
from agno.eval.perf import PerfEval
from smolagents import ToolCallingAgent, HfApiModel, Tool


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



def instantiate_agent():
    return ToolCallingAgent(tools=[WeatherTool()], model=HfApiModel(model_id="meta-llama/Llama-3.3-70B-Instruct"))

smolagents_instantiation = PerfEval(func=instantiate_agent, num_iterations=1000)

if __name__ == "__main__":
    smolagents_instantiation.run(print_results=True)
