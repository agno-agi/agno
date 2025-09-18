from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.os import AgentOS
from agno.tools.mcp import MCPTools

agent = Agent(
    name="Agno Agent",
    model=Claude(id="claude-sonnet-4-0"),
    tools=[MCPTools(transport="streamable-http", url="https://docs.agno.com/mcp")],
)

agent_os = AgentOS(agents=[agent])
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="mcp_demo:app", reload=True)
