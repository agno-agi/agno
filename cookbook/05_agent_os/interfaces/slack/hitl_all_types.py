"""
Slack HITL — all 4 pause types
==============================

Tests Path A Slack HITL with a single agent exposing one tool per pause type:
  • delete_file(path)          → confirmation (requires_confirmation=True)
  • send_email(to, subject)    → user_input (requires_user_input=True)
  • run_shell(command)         → external_execution (external_execution=True)
  • ask_user(questions)        → user_feedback (UserFeedbackTools)

How to exercise each in Slack (DM the bot):
  1. "please delete /tmp/demo.txt"                      → confirmation card
  2. "send an email about Q1 results"                   → user_input form
  3. "run the shell command 'ls -la /tmp'"              → external_execution card
  4. "ask me which pizza toppings I want: pepperoni,
     mushroom, olives. make it multi-select"            → user_feedback checkboxes

For each, fill in / click as needed and press Submit. The agent resumes and
posts the tool's result back into the thread.

Setup:
  export SLACK_TOKEN=xoxb-...
  export SLACK_SIGNING_SECRET=...
  export SSL_CERT_FILE=$(python3 -c "import certifi; print(certifi.where())")
  ngrok http 7777
  # In Slack App config: Event Subscriptions + Interactivity both point at:
  #   <ngrok-url>/slack/events
  #   <ngrok-url>/slack/interactions

  .venvs/demo/bin/python cookbook/05_agent_os/interfaces/slack/hitl_all_types.py
"""

import json
from typing import List

import httpx
from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools import tool
from agno.tools.calculator import CalculatorTools
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.tools.user_feedback import UserFeedbackTools
from agno.tools.wikipedia import WikipediaTools

# ---------------------------------------------------------------------------
# Tools — one per HITL pause type
# ---------------------------------------------------------------------------


@tool(requires_confirmation=True)
def delete_file(path: str) -> str:
    """Delete a file at the given path. Requires human approval before running.

    Args:
        path: Absolute filesystem path to delete.
    """
    # We don't actually delete — just report. Swap to os.remove() if you dare.
    return f"(pretend) Deleted {path}"


@tool(requires_user_input=True, user_input_fields=["to_address", "subject"])
def send_email(to_address: str, subject: str, body: str) -> str:
    """Send an email. The `body` is provided by the agent; `to_address` and
    `subject` are collected from the user at pause time.

    Args:
        to_address: recipient email.
        subject: email subject line.
        body: email body (agent supplies this).
    """
    return f"Sent email to {to_address} with subject {subject!r}: {body[:60]}…"


@tool(external_execution=True)
def run_shell(command: str) -> str:
    """Execute a shell command on an external system. The user pastes the
    output back into the HITL card.

    Args:
        command: shell command to run.
    """
    return f"Would run: {command}"  # Unreachable — external_execution=True pauses first


# ---------------------------------------------------------------------------
# Optional: show real HN data works too (plain tool, no pause)
# ---------------------------------------------------------------------------


@tool
def top_hacker_news_stories(num_stories: int = 3) -> str:
    """Fetch top stories from Hacker News (plain tool, no HITL)."""
    response = httpx.get(
        "https://hacker-news.firebaseio.com/v0/topstories.json", timeout=10
    )
    ids = response.json()[:num_stories]
    stories: List[dict] = []
    for story_id in ids:
        story = httpx.get(
            f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json", timeout=10
        ).json()
        story.pop("text", None)
        stories.append(story)
    return json.dumps(stories, indent=2)


# ---------------------------------------------------------------------------
# Agent + AgentOS + Slack interface
# ---------------------------------------------------------------------------

db = SqliteDb(
    db_file="tmp/hitl_all_types.db",
    session_table="agent_sessions",
    approvals_table="approvals",
)

agent = Agent(
    name="HITL Reference Agent",
    id="hitl-reference-agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
    tools=[
        # HITL pause types
        delete_file,
        send_email,
        run_shell,
        UserFeedbackTools(),
        # Non-pause tools — exercise Slack's streaming task-card UI when
        # multiple tools are invoked back-to-back in a single run.
        top_hacker_news_stories,
        DuckDuckGoTools(),
        HackerNewsTools(),
        WikipediaTools(),
        CalculatorTools(),
    ],
    instructions=[
        "You are a HITL testing assistant. When the user asks you to do something "
        "that matches one of your tools, call the tool — do not ask for confirmation "
        "or clarification yourself; the framework will pause for human input.",
        "For delete_file, call with the provided path.",
        "For send_email, invent a short body and pass to_address + subject as placeholders "
        "(the user will supply the real values via the pause form).",
        "For run_shell, call with the exact command the user gave.",
        "For ask_user, translate the user's description into AskUserQuestion objects "
        "and pass as a list.",
    ],
    markdown=True,
)

agent_os = AgentOS(
    description="Slack HITL — all 4 pause types",
    agents=[agent],
    db=db,
    interfaces=[
        Slack(
            agent=agent,
            hitl_enabled=True,  # v0 HITL on
            approval_authorization="requester_only",  # only the user who triggered can resolve
            reply_to_mentions_only=True,  # channels require @mention; DMs always pass through
        ),
    ],
)
app = agent_os.get_app()


if __name__ == "__main__":
    # Port 7778 matches the existing ngrok tunnel
    # (https://paraphrastic-sang-ingenuous.ngrok-free.dev → localhost:7778).
    agent_os.serve(app="hitl_all_types:app", reload=False, port=7778)
