"""
Slack Agent Messaging Experience
================================

Slack's agent messaging experience on top of a normal Agent: suggested prompts
at the top of the Messages tab, a one-time onboarding message, session status
with a native stop button that only the person who asked can press, and thread
titles that stay in sync with the Agno session name.

Prerequisites: SLACK_TOKEN, SLACK_SIGNING_SECRET, OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/17_slack/agent_messaging.py
Try in Slack: Open the app, pick a suggested prompt, then press Stop mid-answer
Slack scopes: app_mentions:read, assistant:write, chat:write, im:history
Slack events: app_mention, message.im, app_home_opened, app_context_changed,
    agent_session_stopped, agent_session_title_changed
Slack settings: Agents & AI Apps enabled with the Agent view; Interactivity on
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="slack-agent-messaging-db",
    db_file="tmp/slack_agent_messaging.db",
)

researcher = Agent(
    id="slack-research-companion",
    name="Research Companion",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    tools=[WebSearchTools()],
    instructions=[
        "You research questions with web search and answer with sources.",
        "Keep answers scannable: short paragraphs, bullets for lists.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Serve it in Slack
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="slack-agent-messaging-os",
    description="AgentOS demonstrating Slack's agent messaging experience.",
    agents=[researcher],
    interfaces=[
        Slack(
            agent=researcher,
            suggested_prompts=[
                "Give me a three-bullet brief on today's AI news.",
                "Compare two current approaches to Python dependency management.",
                "Explain what Slack agent sessions are, with a source.",
            ],
            onboarding_message="Hi, I am your research companion. Ask me anything, and press Stop if an answer runs long.",
            stop_message="Stopped. Ask again whenever you are ready.",
            loading_text="Researching...",
        )
    ],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Slack AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
