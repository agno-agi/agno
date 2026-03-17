"""
Streaming Workflow on Telegram
==============================

Two-step research-and-write workflow with real-time step progress
in chat. The user sees live status updates as each step runs:

  > Running step: research...
  > Completed step: research
  > Running step: write...

Key concepts:
  - ``streaming=True`` on the Telegram interface enables live progress.
  - ``Steps`` chains sequential ``Step`` objects (research then write).
  - Each step has its own agent with specialised instructions and tools.

Setup:
  1. ``pip install 'agno[telegram,openai]'``
  2. ``export TELEGRAM_TOKEN="..." OPENAI_API_KEY="..."``
  3. Run this file, then expose via ngrok and set the Telegram webhook.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.telegram import Telegram
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.workflow.step import Step
from agno.workflow.steps import Steps
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

db = SqliteDb(
    session_table="telegram_streaming_wf_sessions",
    db_file="tmp/telegram_streaming_workflow.db",
)

researcher = Agent(
    name="Researcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    instructions=[
        "Research the topic using web search.",
        "Provide bullet-point findings with sources.",
    ],
)

writer = Agent(
    name="Writer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=[
        "Write a clear, concise summary from the research.",
        "Use **bold** for key terms and keep it under 300 words.",
        "Suitable for reading on a phone screen.",
    ],
)

research_write_workflow = Workflow(
    name="Research and Write",
    description="Two-step workflow: research a topic, then write a polished summary",
    steps=[
        Steps(
            name="research_and_write",
            description="Research then write",
            steps=[
                Step(
                    name="research", agent=researcher, description="Research the topic"
                ),
                Step(name="write", agent=writer, description="Write the summary"),
            ],
        )
    ],
    db=db,
)

agent_os = AgentOS(
    workflows=[research_write_workflow],
    interfaces=[
        Telegram(
            workflow=research_write_workflow,
            reply_to_mentions_only=False,
            streaming=True,
            start_message="Research bot ready. Send me a topic and I will research and summarize it.",
        )
    ],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run your AgentOS.

    You can see the configuration and available apps at:
    http://localhost:7777/config

    """
    agent_os.serve(app="streaming_workflow:app", reload=True)
