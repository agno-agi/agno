"""
Receive Images and Documents on Microsoft Teams
================================================

Analyze inbound images and supported documents and return a text response.
Generated media is not sent back through this interface yet. Archives are skipped.
Enable supportsFiles in the Teams app manifest as described in README.md.
Prerequisites: OPENAI_API_KEY and the MICROSOFT_APP_* credentials in README.md
Run: python cookbook/05_agent_os/32_msteams/media.py
Try: Paste an image or upload a PDF and ask for a summary.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.msteams import MSTeams

media_agent = Agent(
    id="msteams-media-agent",
    name="Teams Media Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=SqliteDb(id="msteams-media-db", db_file="tmp/msteams_media.db"),
    add_history_to_context=True,
    instructions="Analyze the images and documents the user sends. Reply with concise text.",
)
agent_os = AgentOS(
    id="msteams-media-os",
    agents=[media_agent],
    interfaces=[MSTeams(agent=media_agent)],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app=app)
