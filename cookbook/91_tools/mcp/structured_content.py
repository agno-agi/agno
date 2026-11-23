"""
Structured Content Agent
=============================

Some MCP servers declare an output schema and return their answer as
`structuredContent`. Agno surfaces that payload as the tool output so the agent
can answer from it, and preserves the original typed object on
`ToolResult.metadata["structured_content"]` for hooks and observability.

If a server returns an empty (null) `content` array with only `structuredContent`,
Agno serializes that structured payload into `ToolResult.content` so the model
still sees the result instead of an empty tool message. When `content` already
has text (as DeepWiki returns), that text stays the tool output and the structured
object is kept only in metadata.

This example connects to the hosted DeepWiki MCP server (public, no auth) via
Streamable HTTP. DeepWiki answers questions about any public GitHub repository
and returns its answer as structuredContent. The `structured_content_hook` reads
that typed payload straight from metadata, even though the model only ever sees
`ToolResult.content`.

Example prompts to try:
- "What is the top-level architecture of facebook/react?"
- "How does agno-agi/agno structure its MCP integration?"
- "Summarize the modules in modelcontextprotocol/python-sdk"

Run: `uv pip install agno mcp anthropic` to install the dependencies

Environment variables:
- ANTHROPIC_API_KEY: Required for the default Claude model

Links:
- MCP endpoint: https://mcp.deepwiki.com/mcp
- Docs: https://docs.devin.ai/work-with-devin/deepwiki-mcp
"""

import asyncio
from textwrap import dedent

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.mcp import MCPTools

DEEPWIKI_MCP_URL = "https://mcp.deepwiki.com/mcp"


# ---------------------------------------------------------------------------
# Tool Hook
# ---------------------------------------------------------------------------


async def structured_content_hook(function_name: str, func: callable, args: dict):
    """Access the tool's structuredContent through ToolResult.metadata.

    DeepWiki returns its answer as structuredContent. Agno preserves that object on
    metadata["structured_content"], so this hook can read the typed payload even
    though the model only ever sees ToolResult.content.
    """
    result = await func(**args)
    structured = (getattr(result, "metadata", None) or {}).get("structured_content")
    if structured is not None:
        print(
            f"[structured_content_hook] {function_name} structured_content: {structured}"
        )
    return result


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


async def run_agent(message: str) -> None:
    # DeepWiki's ask_question does deep analysis, so raise the default 10s read timeout.
    async with MCPTools(
        transport="streamable-http", url=DEEPWIKI_MCP_URL, timeout_seconds=60
    ) as deepwiki_tools:
        agent = Agent(
            model=Claude(id="claude-sonnet-4-5"),
            tools=[deepwiki_tools],
            tool_hooks=[structured_content_hook],
            instructions=dedent("""\
                You answer questions about public GitHub repositories using DeepWiki.

                - Use read_wiki_structure to see what a repo's wiki covers
                - Use ask_question for specific questions about a repo
                - Ground your answer in what the tools return; do not invent details
            """),
            markdown=True,
        )
        await agent.aprint_response(input=message, stream=True)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(
        run_agent("In one sentence, what does the facebook/react repository do?")
    )
