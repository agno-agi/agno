from agno.agent import Agent
from agno.models.mistral import MistralChat

# It uses the default model of the Agent
reasoning_agent = Agent(
    model=MistralChat(id="mistral-large-latest"),
    reasoning=True,
    markdown=True,
    use_json_mode=True,
)
reasoning_agent.print_response(
    "Give me steps to write a python script for fibonacci series",
    stream=True,
    show_full_reasoning=True,
)
