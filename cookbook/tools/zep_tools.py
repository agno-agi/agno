import time

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.zep import ZepTools

# Initialize the ZepTools
zep_tools = ZepTools(user_id="agno", session_id="agno-session", add_instructions=True)
zep_tools.initialize()

# Initialize the Agent
agent = Agent(
    model=OpenAIChat(),
    tools=[zep_tools],
    context={"memory": zep_tools.get_zep_memory(memory_type="context")},
    add_context=True,
)

# Interact with the Agent so that it can learn about the user
agent.print_response("My name is John Billings")
agent.print_response("I live in NYC")
agent.print_response("I'm going to a concert tomorrow")

# Allow the memories to sync with Zep database
time.sleep(10)

# Refresh the context
agent.context["memory"] = zep_tools.get_zep_memory(memory_type="context")

# Ask the Agent about the user
agent.print_response("What do you know about me?")
