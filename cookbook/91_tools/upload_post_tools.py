"""
Upload-Post Tools
=============================

Demonstrates publishing a video to several social platforms with Upload-Post.

The publishing tools (upload_video, upload_photos, upload_text) require user
confirmation by default, so the agent pauses before anything goes live.

Requires: UPLOAD_POST_API_KEY and UPLOAD_POST_USER environment variables.
Create an account at https://upload-post.com, connect your social accounts to a
profile, and create an API key. UPLOAD_POST_USER is the profile name.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.upload_post import UploadPostTools
from agno.utils import pprint
from rich.console import Console
from rich.prompt import Prompt

console = Console()

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[UploadPostTools()],
    instructions=[
        "Call list_profiles first to see which platforms are connected.",
        "Only publish to platforms that are connected.",
        "If an upload returns status unknown or processing, check it with get_upload_status. Never publish it again.",
    ],
    markdown=True,
    db=SqliteDb(db_file="tmp/upload_post_tools.db"),
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_response = agent.run(
        "Publish the video tmp/short.mp4 to TikTok and YouTube with the caption "
        "'How agents use tools, in 30 seconds'. Keep the YouTube video private."
    )
    if run_response.is_paused:
        for requirement in run_response.active_requirements:
            if requirement.needs_confirmation:
                console.print(
                    f"Tool [bold blue]{requirement.tool_execution.tool_name}({requirement.tool_execution.tool_args})[/] requires confirmation."
                )
                answer = (
                    Prompt.ask("Publish?", choices=["y", "n"], default="n")
                    .strip()
                    .lower()
                )
                if answer == "y":
                    requirement.confirm()
                else:
                    requirement.reject()

        run_response = agent.continue_run(
            run_id=run_response.run_id,
            requirements=run_response.requirements,
        )
    pprint.pprint_run_response(run_response)
