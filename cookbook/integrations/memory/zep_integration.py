import time

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.zep import ZepTools

# Initialize the ZepTools
zep_tools = ZepTools(user_id="agno", session_id="agno-session")

zep_tools.add_zep_message(role="user", content="My name is John Billings")
zep_tools.add_zep_message(role="user", content="I live in NYC")
zep_tools.add_zep_message(role="user", content="I'm going to a concert tomorrow")

# Allow the memories to sync with Zep database
time.sleep(10)

# Initialize the Agent
agent = Agent(
    model=OpenAIChat(),
    tools=[zep_tools],
    dependencies={"memory": zep_tools.get_zep_memory(memory_type="context")},
    add_dependencies_to_context=True,
)

# Ask the Agent about the user
agent.print_response("What do you know about me?")
