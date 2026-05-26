"""
Slack HITL — User Feedback
==========================

Travel concierge that needs to know a requester's preferences before it
drafts an itinerary. Uses `UserFeedbackTools` so the LLM can call
`ask_user` with structured questions. Slack renders the questions as
Checkboxes (multi-select) or a StaticSelect (single) inside a TaskCard,
and the selections flow back into the agent run when Submit is pressed.
Wikipedia + web search tools give the agent real destination grounding.

Try in Slack:
  @bot help me plan a 5-day trip to Tokyo

Slack scopes: app_mentions:read, assistant:write, chat:write, im:history
"""

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.user_feedback import UserFeedbackTools
from agno.tools.wikipedia import WikipediaTools

# Agent + AgentOS + Slack interface

db = SqliteDb(
    db_file="tmp/hitl_user_feedback.db",
    session_table="agent_sessions",
    approvals_table="approvals",
)

agent = Agent(
    name="Travel Concierge Agent",
    id="travel-concierge-agent",
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
    tools=[
        UserFeedbackTools(),
        WikipediaTools(),
        DuckDuckGoTools(),
    ],
    instructions=[
        "You are a travel concierge.",
        "Workflow: (1) call ask_user ONCE to collect preferences in a single "
        "Slack pause — include at least two questions: interests (multi-select: "
        "museums, food, nightlife, nature, shopping) and travel style (single-"
        "select: budget, mid-range, luxury); (2) after the user submits, use "
        "Wikipedia for destination facts and DuckDuckGo for current-season "
        "events / advisories; (3) draft a day-by-day itinerary aligned to the "
        "stated interests + budget.",
        "Do NOT repeat ask_user mid-plan — ask everything up front so the user "
        "answers once.",
    ],
    markdown=True,
)

agent_os = AgentOS(
    description="Slack HITL — user feedback (travel preferences)",
    agents=[agent],
    db=db,
    interfaces=[
        Slack(
            agent=agent,
            reply_to_mentions_only=True,
        ),
    ],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="hitl_user_feedback:app", reload=True)
