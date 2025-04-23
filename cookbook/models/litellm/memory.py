from agno.agent import Agent
from agno.models.litellm import LiteLLM
from rich.pretty import pprint

agent = Agent(
    model=LiteLLM(id="gpt-4o"),
    # Set add_history_to_messages=true to add the previous chat history to the messages sent to the Model.
    add_history_to_messages=True,
    # Number of historical responses to add to the messages.
    num_history_responses=3,
    description="You are a helpful assistant that always responds in a polite, upbeat and positive manner.",
)

# -*- Create a run
agent.print_response("Share a 2 sentence horror story", stream=True)
# -*- Print the messages in the memory
pprint(
    [
        m.model_dump(include={"role", "content"})
        for m in agent.get_messages_for_session()
    ]
)

# -*- Ask a follow up question that continues the conversation
agent.print_response("What was my first message?", stream=True)
# -*- Print the messages in the memory
pprint(
    [
        m.model_dump(include={"role", "content"})
        for m in agent.get_messages_for_session()
    ]
)
