"""
Comprehensive Slack Test
========================

Two Slack apps (Dash and Ace) running on one server.
Each app gets its own token/signing_secret via the constructor.

Dash (workflow): streaming + parallel research + sequential synthesis
Ace  (team):     streaming + web search + team coordination + markdown

Test scenarios:
  - Workflow streaming: send "Research the latest AI news" (parallel steps + synthesis)
  - Team streaming: use Ace app, send "Research and summarize quantum computing"
  - Agent features tested previously: web search, DALL-E, image input, file input, reasoning

Setup:
  1. Set env vars: DASH_SLACK_TOKEN, DASH_SIGNING_SECRET, ACE_SLACK_TOKEN, ACE_SIGNING_SECRET
  2. Start ngrok: ngrok http 7777
  3. Configure Slack Event Subscriptions:
     - Dash app: https://<ngrok>/dash/events
     - Ace app: https://<ngrok>/ace/events
  4. Required scopes: chat:write, app_mentions:read, im:history, assistant:write,
     files:read, files:write, users:read
  5. Required events: app_mention, message.im, assistant_thread_started

Run:
  .venvs/demo/bin/python cookbook/05_agent_os/interfaces/slack/test_all.py
"""

import os
import ssl

import certifi
from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.team import Team
from agno.tools.dalle import DalleTools
from agno.tools.websearch import WebSearchTools
from agno.workflow import Parallel, Step, Workflow

ssl_context = ssl.create_default_context(cafile=certifi.where())

# ---------------------------------------------------------------------------
# Credentials (explicit per-instance)
# ---------------------------------------------------------------------------

DASH_TOKEN = os.getenv("DASH_SLACK_TOKEN") or os.getenv("SLACK_TOKEN")
DASH_SECRET = os.getenv("DASH_SIGNING_SECRET") or os.getenv("SLACK_SIGNING_SECRET")
ACE_TOKEN = os.getenv("ACE_SLACK_TOKEN") or os.getenv("SLACK_TOKEN")
ACE_SECRET = os.getenv("ACE_SIGNING_SECRET") or os.getenv("SLACK_SIGNING_SECRET")

# ---------------------------------------------------------------------------
# Shared DB
# ---------------------------------------------------------------------------

dash_db = SqliteDb(session_table="dash_sessions", db_file="tmp/test_all.db")
ace_db = SqliteDb(session_table="ace_sessions", db_file="tmp/test_all.db")

# ---------------------------------------------------------------------------
# Dash Agent — streaming + DALL-E + web search + reasoning + markdown
# ---------------------------------------------------------------------------

dash_agent = Agent(
    name="Dash",
    model=Gemini(id="gemini-2.5-flash"),
    tools=[WebSearchTools(), DalleTools()],
    instructions=[
        "You are Dash, a creative assistant with image generation and web search abilities.",
        "When asked to create or generate an image, use DALL-E.",
        "When asked to search, use your web search tools.",
        "When users share files (CSV, PDF, images, video), analyze them thoroughly.",
        "Always format responses with markdown: use **bold**, *italics*, bullet points, and code blocks.",
        "Keep responses concise but informative.",
    ],
    db=dash_db,
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Ace Agent — streaming + web search + reasoning + markdown
# ---------------------------------------------------------------------------

ace_agent = Agent(
    name="Ace",
    model=OpenAIChat(id="gpt-4o"),
    reasoning_model=OpenAIChat(id="o4-mini"),
    tools=[WebSearchTools()],
    instructions=[
        "You are Ace, a research assistant.",
        "When asked to search, use your web search tools.",
        "Always format responses with markdown: use **bold**, *italics*, bullet points, headers, and code blocks.",
        "Provide detailed, well-structured answers.",
    ],
    db=ace_db,
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Team (uses Ace app credentials)
# ---------------------------------------------------------------------------

ace_team = Team(
    name="Ace Team",
    mode="coordinate",
    members=[dash_agent, ace_agent],
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "Coordinate between team members to answer questions.",
        "Dash is a creative assistant with image generation (DALL-E) and web search on Gemini.",
        "Ace is a research assistant with reasoning abilities and web search on GPT-4o.",
        "Delegate image/creative tasks to Dash and research/analysis tasks to Ace.",
    ],
    db=ace_db,
    add_history_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Workflow — parallel research + sequential synthesis (uses Dash app)
# ---------------------------------------------------------------------------

web_search_step = Step(
    name="Web Search",
    agent=dash_agent,
    description="Search the web for relevant information on the topic",
)

analysis_step = Step(
    name="Deep Analysis",
    agent=ace_agent,
    description="Analyze the topic from a research perspective",
)

research_phase = Parallel(
    web_search_step,
    analysis_step,
    name="Research Phase",
)

synthesis_step = Step(
    name="Final Summary",
    agent=ace_agent,
    description="Synthesize all research into a comprehensive final summary",
)

dash_workflow = Workflow(
    name="Research Pipeline",
    steps=[research_phase, synthesis_step],
    db=dash_db,
)

# ---------------------------------------------------------------------------
# AgentOS — two apps, explicit credentials
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    agents=[dash_agent, ace_agent],
    teams=[ace_team],
    workflows=[dash_workflow],
    interfaces=[
        # Dash app — workflow with parallel research + synthesis
        Slack(
            workflow=dash_workflow,
            prefix="/dash",
            token=DASH_TOKEN,
            signing_secret=DASH_SECRET,
            streaming=True,
            reply_to_mentions_only=True,
            loading_messages=[
                "Thinking...",
                "Searching the web...",
                "Working on it...",
            ],
            suggested_prompts=[
                {"title": "Help", "message": "What can you help me with?"},
                {"title": "Search", "message": "Search the web for the latest news"},
            ],
            ssl=ssl_context,
        ),
        # Ace app — team with Researcher + Writer coordination
        Slack(
            team=ace_team,
            prefix="/ace",
            token=ACE_TOKEN,
            signing_secret=ACE_SECRET,
            streaming=True,
            reply_to_mentions_only=True,
            loading_messages=[
                "Thinking...",
                "Researching...",
                "Almost there...",
            ],
            suggested_prompts=[
                {"title": "Research", "message": "Research a topic for me"},
                {"title": "Summarize", "message": "Summarize the latest tech news"},
            ],
            ssl=ssl_context,
        ),
    ],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="test_all:app", reload=True, port=7777)
