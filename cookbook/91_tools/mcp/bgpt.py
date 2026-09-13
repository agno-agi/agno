"""MCP BGPT Agent - Evidence-grounded scientific paper search.

This example connects to the hosted BGPT MCP server via Streamable HTTP.
BGPT returns structured evidence fields (methods, sample sizes, limitations,
conflicts of interest, falsifiability) extracted from full-text papers—not
just titles or abstracts.

Example prompts to try:
- "Search for papers on CAR-T response rates and summarize study limitations"
- "Look up DOI 10.1038/s41586-024-07386-0 and list conflicts of interest"
- "What does the literature say about GLP-1 cardiovascular outcomes?"

Run: `uv pip install agno mcp anthropic` to install the dependencies

Environment variables:
- ANTHROPIC_API_KEY: Required for the default Claude model
- BGPT_API_KEY: Optional Stripe subscription ID for >50 results (free tier needs no key)

Links:
- MCP endpoint: https://bgpt.pro/mcp/stream
- Docs: https://bgpt.pro/mcp/
- GitHub: https://github.com/connerlambden/bgpt-mcp
"""

import asyncio
from os import getenv
from textwrap import dedent

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.mcp import MCPTools
from agno.tools.mcp.params import StreamableHTTPClientParams

BGPT_MCP_URL = "https://bgpt.pro/mcp/stream"


def _mcp_tools() -> MCPTools:
    api_key = getenv("BGPT_API_KEY")
    if api_key:
        return MCPTools(
            transport="streamable-http",
            server_params=StreamableHTTPClientParams(
                url=BGPT_MCP_URL,
                headers={"Authorization": f"Bearer {api_key}"},
            ),
        )
    return MCPTools(transport="streamable-http", url=BGPT_MCP_URL)


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


async def run_agent(message: str) -> None:
    async with _mcp_tools() as bgpt_tools:
        agent = Agent(
            model=Claude(id="claude-sonnet-4-5"),
            tools=[bgpt_tools],
            instructions=dedent("""\
                You are a research evidence assistant powered by BGPT.

                When searching literature:
                - Cite DOIs and publication dates
                - Surface limitations, biases, and conflicts of interest
                - Note sample sizes and whether claims are falsifiable
                - Do not overstate conclusions beyond what the evidence supports

                Use search_papers for keyword search and lookup_paper for DOIs.
            """),
            markdown=True,
        )
        await agent.aprint_response(input=message, stream=True)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(
        run_agent(
            "Search for 3 papers on semaglutide cardiovascular outcomes. "
            "For each, summarize methods, limitations, and conflicts of interest."
        )
    )
