"""Telegram workflow with streaming step progress.

Shows real-time step progress in chat:
  > Running step: research...
  > Completed step: research
  > Running step: write...
  > Completed step: write

Usage:
  1. pip install 'agno[telegram,openai]'
  2. Export env vars:
       export TELEGRAM_TOKEN="<your-bot-token>"
       export OPENAI_API_KEY="<your-key>"
  3. Start server:
       python cookbook/05_agent_os/interfaces/telegram/streaming_workflow.py
  4. Start ngrok:
       ngrok http 7777
  5. Set webhook:
       curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook?url=<NGROK_URL>/telegram/webhook"
  6. Message the bot in Telegram and watch step progress appear in real-time.
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
            stream=True,
            start_message="Research bot ready. Send me a topic and I will research and summarize it.",
        )
    ],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="streaming_workflow:app", reload=True)
