from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    name="Agent with Tools",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    instructions="""
    You are a versatile AI assistant with the following capabilities:

    **Tools (executed on server):**
    - Web search using DuckDuckGo for finding current information

    Always be helpful, creative, and use the most appropriate tool for each request!
    """,
    add_datetime_to_context=True,
    add_history_to_context=True,
    add_location_to_context=True,
    timezone_identifier="Etc/UTC",
    markdown=True,
    debug_mode=True,
)


# Setup your AgentOS app
agent_os = AgentOS(
    agents=[agent],
    a2a_interface=True,
)
app = agent_os.get_app()


if __name__ == "__main__":
    """Run your AgentOS.

    You can run the Agent via A2A protocol:
    POST http://localhost:7777/a2a/message/send
    (include "agentId": "agent-with-tools" in params.message)
    """
    agent_os.serve(app="agent_with_tools:app", port=7777, reload=True)
