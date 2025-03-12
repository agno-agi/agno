from agno.agent import Agent
from agno.models.openai import OpenAIChat

task = (
    "You are a train conductor faced with an emergency: the brakes have failed, and the train is heading towards "
    "five people tied on the track. You can divert the train onto another track, but there is one person tied there. "
    "Do you divert the train, sacrificing one to save five? Provide a well-reasoned answer considering utilitarian "
    "and deontological ethical frameworks. "
    "Provide your answer also as an ascii art diagram."
)

reasoning_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    reasoning=True,
    markdown=True,
)
reasoning_agent.print_response(task, stream=True, show_full_reasoning=True)
