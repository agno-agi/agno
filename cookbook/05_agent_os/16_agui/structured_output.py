"""
Stream Structured Output over AG-UI
===================================

Give an AG-UI agent a Pydantic output schema so the streamed response follows
one predictable movie-pitch structure.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/16_agui/structured_output.py
Try: POST "Pitch a lunar mystery" to http://localhost:7777/structured-output/agui
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Create Structured Agent
# ---------------------------------------------------------------------------


class MoviePitch(BaseModel):
    title: str = Field(description="A short movie title.")
    genre: str = Field(description="The movie genre.")
    setting: str = Field(description="Where and when the story takes place.")
    characters: list[str] = Field(description="The main character names.")
    storyline: str = Field(description="A three-sentence storyline.")


db = SqliteDb(
    id="agui-structured-output-db",
    db_file="tmp/agui_structured_output.db",
)

script_writer = Agent(
    id="agui-script-writer",
    name="AG-UI Script Writer",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    output_schema=MoviePitch,
    instructions="Turn each request into an original, internally consistent movie pitch.",
)

agent_os = AgentOS(
    id="agui-structured-output-os",
    description="AG-UI streaming a Pydantic-validated response.",
    agents=[script_writer],
    interfaces=[AGUI(agent=script_writer, prefix="/structured-output")],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Structured Output Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
