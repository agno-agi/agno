import asyncio

from agents import run_research
from mcp.server.fastmcp import FastMCP

# Create FastMCP instance
mcp = FastMCP("deep_researcher_agent")


@mcp.tool()
def deep_researcher_agent(query: str) -> str:
    """Run Deep Researcher Agent for given user query. Can do both standard and deep web search.

    Args:
        query (str): The research query or question.

    Returns:
        str: The research response from the Deep Researcher Agent.
    """

    return run_research(query)


# Run the server
if __name__ == "__main__":
    mcp.run(transport="stdio")


# add this inside ./.cursor/mcp.json
# {
#   "mcpServers": {
#     "deep_researcher_agent": {
#       "command": "python",
#       "args": [
#         "--directory",
#         "/Users/arindammajumder/Developer/Python/awesome-llm-apps/advance_ai_agents/deep_researcher_agent",
#         "run",
#         "server.py"
#       ],
#       "env": {
#         "NEBIUS_API_KEY": "your_nebius_api_key_here",
#         "SGAI_API_KEY": "your_scrapegraph_api_key_here"
#       }
#     }
#   }
# }
