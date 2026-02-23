"""
Streaming Events Test
=====================

Comprehensive test for all Slack streaming event handlers.
Switch between agent/team/workflow with TEST_MODE env var.
One bot, one /slack endpoint.

Setup:
  1. Set env vars: SLACK_TOKEN, SLACK_SIGNING_SECRET
  2. Start ngrok: ngrok http 7777
  3. Set Event Subscription URL: https://<ngrok>/slack/events
  4. Subscribe to: app_mention, message.im, assistant_thread_started
  5. Required scopes: chat:write, app_mentions:read, im:history,
     assistant:write, files:read, files:write, users:read

Run:
  # Agent with reasoning model + tools
  TEST_MODE=agent .venvs/demo/bin/python cookbook/05_agent_os/interfaces/slack/test_streaming_events.py

  # Coordinate team with 2 members
  TEST_MODE=team .venvs/demo/bin/python cookbook/05_agent_os/interfaces/slack/test_streaming_events.py

  # Workflow with Parallel + Condition
  TEST_MODE=workflow .venvs/demo/bin/python cookbook/05_agent_os/interfaces/slack/test_streaming_events.py

Test prompts:
  Agent:    "Search for the latest AI news and analyze the trends"
  Team:     "Research quantum computing breakthroughs and write a summary"
  Workflow: "Write an article about climate technology startups"
"""

import os
import sys

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.team import Team
from agno.tools.hackernews import HackerNewsTools
from agno.tools.websearch import WebSearchTools
from agno.workflow.condition import Condition
from agno.workflow.parallel import Parallel
from agno.workflow.step import Step
from agno.workflow.types import StepInput
from agno.workflow.workflow import Workflow

TEST_MODE = os.getenv("TEST_MODE", "agent")
db = SqliteDb(session_table="streaming_events", db_file="tmp/streaming_events.db")


# ---------------------------------------------------------------------------
# Agent — reasoning steps + tool calls + content streaming
# ---------------------------------------------------------------------------
def build_agent():
    agent = Agent(
        name="Research Analyst",
        model=OpenAIChat(id="gpt-4o"),
        reasoning_model=OpenAIChat(id="o4-mini"),
        tools=[WebSearchTools(), HackerNewsTools()],
        instructions=[
            "You are a research analyst with web search and HackerNews access.",
            "Think step by step before answering.",
            "Use tables and markdown formatting in your responses.",
        ],
        db=db,
        add_history_to_context=True,
        num_history_runs=3,
        add_datetime_to_context=True,
        markdown=True,
    )
    return AgentOS(
        agents=[agent],
        interfaces=[
            Slack(
                agent=agent,
                streaming=True,
                reply_to_mentions_only=True,
                loading_messages=["Thinking...", "Searching...", "Analyzing..."],
                suggested_prompts=[
                    {
                        "title": "AI News",
                        "message": "Search for the latest AI news and analyze the trends",
                    },
                    {
                        "title": "HN Trends",
                        "message": "What are the top trending topics on HackerNews?",
                    },
                ],
            )
        ],
    )


# ---------------------------------------------------------------------------
# Team — member events + member tool calls
# ---------------------------------------------------------------------------
def build_team():
    researcher = Agent(
        name="Researcher",
        role="Web research specialist",
        model=OpenAIChat(id="gpt-4o"),
        tools=[WebSearchTools(), HackerNewsTools()],
        instructions=[
            "You are a research specialist. Search the web and HackerNews thoroughly.",
            "Return detailed findings with sources.",
        ],
        markdown=True,
    )
    writer = Agent(
        name="Writer",
        role="Content writer and editor",
        model=OpenAIChat(id="gpt-4o"),
        instructions=[
            "You are a content writer. Create engaging, well-structured content.",
            "Use headings, bullet points, and clear conclusions.",
        ],
        markdown=True,
    )
    team = Team(
        name="Research Team",
        mode="coordinate",
        model=OpenAIChat(id="gpt-4o"),
        members=[researcher, writer],
        instructions=[
            "Coordinate between Researcher and Writer to answer questions.",
            "Have the Researcher gather information first, then the Writer creates the final output.",
        ],
        db=db,
        add_history_to_context=True,
        markdown=True,
    )
    return AgentOS(
        teams=[team],
        interfaces=[
            Slack(
                team=team,
                streaming=True,
                reply_to_mentions_only=True,
                loading_messages=[
                    "Coordinating team...",
                    "Researching...",
                    "Writing...",
                ],
                suggested_prompts=[
                    {
                        "title": "Research",
                        "message": "Research quantum computing breakthroughs and write a summary",
                    },
                    {
                        "title": "Compare",
                        "message": "Compare React and Vue for building web apps",
                    },
                ],
            )
        ],
    )


# ---------------------------------------------------------------------------
# Workflow — Parallel + Condition (step/parallel/condition events)
# ---------------------------------------------------------------------------
def build_workflow():
    wf_researcher = Agent(
        name="WF Researcher",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[WebSearchTools()],
        instructions="Research the given topic thoroughly from web sources.",
    )
    wf_hn_researcher = Agent(
        name="WF HN Researcher",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[HackerNewsTools()],
        instructions="Research the topic from HackerNews discussions and trends.",
    )
    wf_fact_checker = Agent(
        name="WF Fact Checker",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[WebSearchTools()],
        instructions="Verify facts and claims. Search for confirming or contradicting evidence.",
    )
    wf_writer = Agent(
        name="WF Writer",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="Write a comprehensive article based on all research and verification.",
    )

    research_web_step = Step(name="Research Web", agent=wf_researcher)
    research_hn_step = Step(name="Research HackerNews", agent=wf_hn_researcher)
    fact_check_step = Step(name="Fact Check", agent=wf_fact_checker)
    write_step = Step(name="Write Article", agent=wf_writer)

    def needs_fact_checking(step_input: StepInput) -> bool:
        content = step_input.previous_step_content or ""
        indicators = [
            "study",
            "research",
            "according",
            "percent",
            "%",
            "million",
            "billion",
            "report",
        ]
        return any(ind in content.lower() for ind in indicators)

    workflow = Workflow(
        name="Content Pipeline",
        description="Parallel research -> conditional fact-check -> write article",
        steps=[
            Parallel(research_web_step, research_hn_step, name="Research Phase"),
            Condition(
                name="Fact Check Gate",
                evaluator=needs_fact_checking,
                steps=[fact_check_step],
            ),
            write_step,
        ],
        db=db,
    )
    return AgentOS(
        workflows=[workflow],
        interfaces=[
            Slack(
                workflow=workflow,
                streaming=True,
                reply_to_mentions_only=True,
                loading_messages=[
                    "Starting workflow...",
                    "Researching...",
                    "Writing...",
                ],
                suggested_prompts=[
                    {
                        "title": "Article",
                        "message": "Write an article about climate technology startups",
                    },
                    {
                        "title": "Deep Dive",
                        "message": "Research and write about the state of AI in healthcare",
                    },
                ],
            )
        ],
    )


# ---------------------------------------------------------------------------
# Build the selected mode
# ---------------------------------------------------------------------------
BUILDERS = {"agent": build_agent, "team": build_team, "workflow": build_workflow}

builder = BUILDERS.get(TEST_MODE)
if builder is None:
    print(f"Unknown TEST_MODE={TEST_MODE!r}. Use: agent, team, or workflow")
    sys.exit(1)

print(f"Starting in {TEST_MODE} mode...")
agent_os = builder()
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="test_streaming_events:app", reload=True, port=8000)
