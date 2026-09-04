"""
Basic Microsoft 365 Copilot Agent
================================

Minimal example of exposing an Agno agent to Microsoft 365 Copilot
via the M365 Copilot interface.

Key concepts:
  - M365Copilot interface exposes agents to Microsoft 365 Copilot
  - Generates OpenAPI specification for plugin registration
  - Validates Microsoft Entra ID JWT tokens
  - Allows Copilot to invoke agents for specialized tasks

Environment Variables:
  - M365_TENANT_ID: Microsoft Entra ID tenant ID (required)
  - M365_CLIENT_ID: Application client ID for token validation (required)

Usage:
  1. Set environment variables for M365 configuration
  2. Run this script to start the AgentOS server
  3. Use the OpenAPI spec from /m365/manifest to register in Copilot Studio
  4. Invoke the agent from Microsoft 365 Copilot

OpenAPI Specification:
  GET http://localhost:7777/m365/manifest

Agent Discovery:
  GET http://localhost:7777/m365/agents

Invoke Agent:
  POST http://localhost:7777/m365/invoke/{agent_id}
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.m365 import M365Copilot

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Create a specialized financial analyst agent
financial_agent = Agent(
    agent_id="financial-analyst",
    name="Financial Analyst",
    model=OpenAIChat(id="gpt-4o"),
    instructions="""
    You are a specialized financial analyst for CENF.

    Your responsibilities:
    - Analyze financial reports and statements
    - Identify trends and anomalies in financial data
    - Generate financial insights and recommendations
    - Create summaries for stakeholders

    Best practices:
    - Always provide data-backed insights
    - Cite specific numbers and percentages
    - Highlight important trends and anomalies
    - Use clear, professional language

    When responding:
    - Start with an executive summary
    - Provide detailed analysis
    - Include actionable recommendations
    - Flag any concerns or areas needing attention
    """,
    mark_delimiter="```",
)

# ---------------------------------------------------------------------------
# Setup AgentOS with M365 Interface
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    agents=[financial_agent],
    interfaces=[
        M365Copilot(
            agent=financial_agent,
            # Optional: Custom agent descriptions for Copilot Studio
            agent_descriptions={
                "financial-analyst": (
                    "Expert financial analyst specializing in report analysis, "
                    "trend identification, and generating actionable insights "
                    "from financial data."
                )
            },
            # Optional: Customize OpenAPI specification
            api_title="CENF Financial Agents",
            api_description="Specialized AI agents for financial analysis and reporting",
        )
    ],
)

app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """
    Run the AgentOS server.

    The server will start on http://localhost:7777

    Available endpoints:
      - http://localhost:7777/config    - View AgentOS configuration
      - http://localhost:7777/m365/manifest - Get OpenAPI specification
      - http://localhost:7777/m365/agents    - List available agents
      - http://localhost:7777/m365/health    - Health check

    To register in Copilot Studio:
      1. GET http://localhost:7777/m365/manifest
      2. Copy the OpenAPI specification
      3. Paste into Copilot Studio plugin configuration
      4. Configure authentication (Bearer token, Microsoft Entra ID)
    """
    agent_os.serve(app="basic:app", reload=True)
