from textwrap import dedent

from agno.agent import Agent
from agno.os import AgentOS
from agno.tools.mcp_toolbox import MCPToolbox

url = "http://127.0.0.1:5001"

mcp_database_tools = MCPToolbox(
    url=url, toolsets=["hotel-management", "booking-system"]
)

agent = Agent(
    tools=[mcp_database_tools],
    instructions=dedent(
        """ \
        You're a helpful hotel assistant. You handle hotel searching, booking and
        cancellations. When the user searches for a hotel, mention it's name, id,
        location and price tier. Always mention hotel ids while performing any
        searches. This is very important for any operations. For any bookings or
        cancellations, please provide the appropriate confirmation. Be sure to
        update checkin or checkout dates if mentioned by the user.
        Don't ask for confirmations from the user.
    """
    ),
    markdown=True,
)


agent_os = AgentOS(
    name="Hotel Assistant",
    description="An agent that helps users find and book hotels.",
    agents=[agent],
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="agent_os:app", reload=True)
