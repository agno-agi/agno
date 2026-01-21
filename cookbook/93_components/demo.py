"""
This cookbook demonstrates how to use a registry with the AgentOS app.
"""

from agno.db.postgres import PostgresDb
from agno.models.anthropic import Claude
from agno.models.google.gemini import Gemini
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.registry import Registry
from agno.tools.calculator import CalculatorTools
from agno.tools.parallel import ParallelTools
from agno.tools.youtube import YouTubeTools
from pydantic import BaseModel

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai", id="postgres_db")


def custom_function(input: str) -> str:
    return input + "Hello, world!"


class CustomInputSchema(BaseModel):
    input: str
    description: str


class CustomOutputSchema(BaseModel):
    output: str
    description: str


registry = Registry(
    name="Agno Registry",
    tools=[ParallelTools(), CalculatorTools(), YouTubeTools()],
    functions=[custom_function],
    schemas=[CustomInputSchema, CustomOutputSchema],
    models=[
        OpenAIChat(id="gpt-5-mini"),
        OpenAIChat(id="gpt-5"),
        Claude(id="claude-sonnet-4-5"),
        Gemini(id="gemini-3-flash-preview"),
    ],
    dbs=[db],
)

agent_os = AgentOS(
    id="demo-agent-os",
    registry=registry,
    db=db,
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="demo:app", reload=True)
