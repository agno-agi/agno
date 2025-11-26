from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools

agent = Agent(
    model=OpenAIResponses(id="gpt-5.1"),
    tools=[ParallelTools()],
    instructions="No need to tell me its based on your research.",
    markdown=True,
)

agent.print_response(
    "Tell me about Agno's AgentOS?",
    stream=True,
    stream_events=True,
)
