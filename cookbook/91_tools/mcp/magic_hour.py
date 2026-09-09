"""Magic Hour MCP Agent - Generate AI Images and Videos

Connect an Agno agent to Magic Hour's hosted MCP server. The server exposes
image, video, and audio generation tools plus project-status helpers.

Setup:
1. Install dependencies: `uv pip install "agno[mcp,openai]"`
2. Create a Magic Hour API key at https://magichour.ai/developer
3. Set `MAGIC_HOUR_API_KEY` and `OPENAI_API_KEY` in your environment

Run: `python cookbook/91_tools/mcp/magic_hour.py`

Magic Hour MCP docs: https://docs.magichour.ai/integration/model-context-protocol
"""

import asyncio
from os import getenv
from pathlib import Path
from textwrap import dedent
from typing import Optional
from urllib.parse import urlparse

import httpx
from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.mcp import MCPTools
from agno.utils.log import log_error, log_info
from pydantic import BaseModel

MAGIC_HOUR_MCP_URL = "https://mcp.magichour.ai/"


class MediaResult(BaseModel):
    project_id: str
    download_url: str
    summary: str


async def run_agent(task: str) -> None:
    """Connect to Magic Hour and run one media-generation task."""
    magic_hour_api_key = getenv("MAGIC_HOUR_API_KEY")
    if not magic_hour_api_key:
        log_error("MAGIC_HOUR_API_KEY environment variable not set.")
        return

    async with MCPTools(
        url=MAGIC_HOUR_MCP_URL,
        transport="streamable-http",
        headers={"Authorization": f"Bearer {magic_hour_api_key}"},
        timeout_seconds=600,
    ) as magic_hour_tools:
        agent = Agent(
            name="MagicHourAgent",
            model=OpenAIResponses(id="gpt-5.6-luna", parallel_tool_calls=False),
            tools=[magic_hour_tools],
            output_schema=MediaResult,
            # Keep the final response structured without forcing OpenAI's strict
            # schema rules onto externally defined MCP tool schemas.
            use_json_mode=True,
            instructions=dedent("""\
                You create media with Magic Hour's tools.

                - Choose the creation tool that matches the requested media
                - Call the creation tool once and only once; every call bills credits
                - Request 640px resolution unless the user asks for something larger,
                  since higher resolutions need a paid Magic Hour plan
                - If a call is rejected, report why instead of retrying with different
                  settings; a retry that succeeds bills a second project
                - Retain the returned project ID
                - Call the matching wait_for_*_project tool until it reaches a terminal state
                - If waiting times out, resume with the same project ID; do not create a duplicate
                - Report terminal errors clearly and never claim completion without an output URL
                - Copy the download URL exactly; its query parameters are a signature
                  and stop working if altered
            """),
        )
        await agent.aprint_response(input=task, stream=True)

        run_output = await agent.aget_last_run_output()
        result: Optional[MediaResult] = getattr(run_output, "content", None)
        if not isinstance(result, MediaResult):
            log_error("Agent did not return a MediaResult.")
            return

        print(result.download_url)

        output_path = (
            Path(__file__).parent
            / "tmp"
            / Path(urlparse(result.download_url).path).name
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.get(result.download_url)
            response.raise_for_status()
            output_path.write_bytes(response.content)
        log_info(f"Saved {output_path}")


if __name__ == "__main__":
    asyncio.run(
        run_agent(
            "Create a square product image of a ceramic coffee mug on a warm studio "
            "background. Wait for completion and return the final image URL."
        )
    )

# More example prompts:
"""
- "Animate this product photo into a five-second video with a slow camera push-in: <public image URL>"
- "Create a 16:9 cinematic video of a neon ramen shop in the rain. Wait for the final video."
- "Generate a campaign image from this approved brief, then return the project ID and final image URL."
"""
