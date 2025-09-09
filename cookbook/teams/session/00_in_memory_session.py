from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team import Team
from rich.pretty import pprint

agent = Agent(
    model=OpenAIChat(id="o3-mini"),
)

team = Team(
    model=OpenAIChat(id="o3-mini"),
    members=[agent],
)


# -*- Create a run
team.print_response("Share a 2 sentence horror story", stream=True)
# -*- Print the messages in the memory
pprint(
    [
        m.model_dump(include={"role", "content"})
        for m in agent.get_messages_for_session()
    ]
)

# -*- Ask a follow up question that continues the conversation
team.print_response("What was my first message?", stream=True)
# -*- Print the messages in the memory
pprint(
    [
        m.model_dump(include={"role", "content"})
        for m in agent.get_messages_for_session()
    ]
)
