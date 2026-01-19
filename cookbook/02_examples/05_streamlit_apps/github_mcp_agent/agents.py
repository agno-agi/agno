import os
from textwrap import dedent

from agno.agent import Agent
from agno.tools.mcp import MCPTools
from agno.utils.log import logger
from agno.utils.streamlit import get_model_from_id


async def run_github_agent(message: str, model_id: str = "gpt-4o"):
    if not os.getenv("GITHUB_TOKEN"):
        return "Error: GitHub token not provided"

    try:
        # Initialize MCP toolkit
        async with MCPTools(
            command="npx -y @modelcontextprotocol/server-github"
        ) as mcp_tools:
            model = get_model_from_id(model_id)

            # Create agent
            agent = Agent(
                tools=[mcp_tools],
                model=model,
                instructions=dedent("""\
                    You are a GitHub assistant. Help users explore repositories and their activity.
                    - Provide organized, concise insights about the repository
                    - Focus on facts and data from the GitHub API
                    - Use markdown formatting for better readability
                    - Present numerical data in tables when appropriate
                    - Include links to relevant GitHub pages when helpful
                """),
                markdown=True,
            )

            # Run agent
            response = await agent.arun(message)
            return response.content
    except Exception as e:
        logger.error(f"Error running GitHub MCP agent: {e}")
        return f"Error: {str(e)}"
