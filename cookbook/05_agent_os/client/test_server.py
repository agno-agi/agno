"""Minimal AgentOS server with SSE test page served from same origin."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.tools.calculator import CalculatorTools

db = SqliteDb(db_file="tmp/sse_test.db")

agent = Agent(
    name="Assistant",
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
    instructions=["You are a helpful assistant. When asked to write something long, write at least 500 words."],
    tools=[CalculatorTools()],
    markdown=True,
)

agent_os = AgentOS(
    id="sse-test-server",
    agents=[agent],
)

app = agent_os.get_app()

# Serve test HTML from same origin (no CORS issues)
@app.get("/test", response_class=HTMLResponse)
async def test_page():
    html_path = Path(__file__).parent / "sse_test.html"
    return HTMLResponse(content=html_path.read_text())


if __name__ == "__main__":
    agent_os.serve(app="test_server:app", reload=True)
