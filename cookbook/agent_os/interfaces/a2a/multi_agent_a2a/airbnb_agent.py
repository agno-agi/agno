from textwrap import dedent
from agno.agent import Agent
from agno.os import AgentOS
from agno.models.openai import OpenAIChat
from agno.tools.mcp import MCPTools


airbnb_agent = Agent(
    id="airbnb-search-agent",
    name="Airbnb Search Agent",
    description="A specialized agent for finding and detailing Airbnb listings using the OpenBNB MCP server.",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        MCPTools(
            "npx -y @openbnb/mcp-server-airbnb --ignore-robots-txt"
        )
    ],
    instructions=dedent("""
        You are an expert travel assistant.
        Use the 'airbnb_search' tool to find properties based on location, dates, and people.
        For detailed listing information, use 'airbnb_listing_details'.
        Always provide location, price, and a link in your final response.
    """),
    markdown=False,
)

agent_os = AgentOS(
    id="airbnb-agent-os",
    description="An AgentOS serving specialized Agent for Airbnb search",
    agents=[
        airbnb_agent,
    ],a2a_interface=True
)
app = agent_os.get_app()


if __name__ == "__main__":
    """Run your AgentOS.
    You can run the Agent via A2A protocol:
    POST http://localhost:7777/a2a/message/send
    (include "agentId": "agent-with-tools" in params.message)
    """
    agent_os.serve(app="airbnb_agent:app", port=7774, reload=True)