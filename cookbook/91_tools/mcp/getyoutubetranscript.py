"""GetYouTubeTranscript MCP Agent - Read and Research YouTube Videos

Connect an Agno agent to GetYouTubeTranscript's hosted MCP server. The server
exposes YouTube transcripts in any caption language a video has (optionally
timestamped or machine-translated), YouTube search, and channel, playlist and
video data.

Setup:
1. Install dependencies: `uv pip install "agno[mcp,openai]"`
2. Create a GetYouTubeTranscript API key at https://getyoutubetranscript.com/developers
   (a new account gets 100 credits)
3. Set `GETYOUTUBETRANSCRIPT_API_KEY` and `OPENAI_API_KEY` in your environment

Run: `python cookbook/91_tools/mcp/getyoutubetranscript.py`

GetYouTubeTranscript MCP docs: https://github.com/tubeagentkit/youtube-mcp
"""

import asyncio
from os import getenv
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.mcp import MCPTools
from agno.utils.log import log_error

GETYOUTUBETRANSCRIPT_MCP_URL = "https://getyoutubetranscript.com/api/mcp"


async def run_agent(task: str) -> None:
    """Connect to GetYouTubeTranscript and run one research task."""
    api_key = getenv("GETYOUTUBETRANSCRIPT_API_KEY")
    if not api_key:
        log_error("GETYOUTUBETRANSCRIPT_API_KEY environment variable not set.")
        return

    async with MCPTools(
        url=GETYOUTUBETRANSCRIPT_MCP_URL,
        transport="streamable-http",
        headers={"Authorization": f"Bearer {api_key}"},
    ) as youtube_tools:
        agent = Agent(
            name="YouTubeResearchAgent",
            model=OpenAIResponses(id="gpt-5.6-luna"),
            tools=[youtube_tools],
            markdown=True,
            instructions=dedent("""\
                You research YouTube videos with GetYouTubeTranscript's tools.

                - Fetch a transcript before summarizing or quoting a video; never
                  answer from the title alone
                - Request timestamps when you quote, and cite each quote with its
                  time and a link to that moment
                - Most calls cost 1 credit, so fetch each transcript once and reuse it
                - If a video has no captions, say so; there is no transcript to read
                - Check the returned language_code: it is the caption track you got,
                  which can differ from the language you asked for
            """),
        )
        await agent.aprint_response(input=task, stream=True)


if __name__ == "__main__":
    asyncio.run(
        run_agent(
            "Summarize https://www.youtube.com/watch?v=dQw4w9WgXcQ in five bullet "
            "points and quote the chorus with its timestamp."
        )
    )

# More example queries:
"""
- "Search YouTube for talks about vector databases from the last year and summarize the top three."
- "List the latest five uploads from @veritasium and give me one line on each."
- "What does the speaker say about pricing in this video? Quote it with timestamps: <YouTube URL>"
- "Get the Spanish captions for this video, or translate the English ones if there are none: <YouTube URL>"
"""
