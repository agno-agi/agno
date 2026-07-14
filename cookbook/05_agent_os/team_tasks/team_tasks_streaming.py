"""Team Task Streaming Demo with AgentOS

This example demonstrates how to expose a Team running in `tasks` mode via AgentOS.
You can use the AgentOS API to send requests and test task streaming.

Usage:
    uv run cookbook/05_agent_os/team_tasks_streaming.py

    Then you can test streaming using curl:
    curl -X POST http://0.0.0.0:7777/v1/teams/research-team/runs/stream \
         -H "Content-Type: application/json" \
         -d '{"message": "What are the key benefits of microservices architecture?"}'
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team.mode import TeamMode
from agno.team.team import Team

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------

researcher = Agent(
    name="Researcher",
    role="Researches topics and gathers information",
    model=OpenAIChat(id="gpt-5-mini"),
    db=db,
    instructions=[
        "Research the given topic thoroughly.",
        "Provide factual information.",
    ],
)

summarizer = Agent(
    name="Summarizer",
    role="Summarizes information into concise points",
    model=OpenAIChat(id="gpt-5-mini"),
    db=db,
    instructions=["Create clear, concise summaries.", "Highlight key points."],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------

team = Team(
    id="research-team",
    name="Research Team",
    mode=TeamMode.tasks,
    model=OpenAIChat(id="gpt-5-mini"),
    members=[researcher, summarizer],
    db=db,
    instructions=[
        "You are a research team leader. Follow these steps exactly:",
        "1. Create ALL tasks for the Researcher to gather information.",
        "2. Create ALL tasks for the Summarizer to summarize the research.",
        "3. Execute the Researcher's task.",
        "4. Execute the Summarizer's task.",
        "5. Call mark_all_complete with a final summary when all tasks are done.",
    ],
    max_iterations=3,
)

# ---------------------------------------------------------------------------
# AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    name="Team Tasks Streaming Demo",
    teams=[team],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="team_tasks_streaming:app", port=7777, reload=True)
