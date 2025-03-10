# 1. CEO Agent (Leader) – Sets vision, prioritizes tasks, and makes strategic decisions.
# 2. Product Manager Agent – Defines product roadmap, gathers user feedback, and refines features.
# 3. Marketing Manager Agent – Develops branding, runs campaigns, and tracks audience engagement.
# 4. Designer Agent – Creates UI/UX mockups, branding assets, and product visuals.
# 5. Financial Analyst Agent – Handles revenue projections, pricing strategies, and investor reports.
# 6.  Market Research Agent – Analyzes industry trends, competitors, and customer demands.
# 7. Legal Compliance Agent – Ensures contracts, policies, and regulations are met.
# 8. Sales & Partnerships Agent – Identifies leads, negotiates deals, and tracks conversions.
# 9.  Customer Support Agent – Engages with users, handles tickets, and improves customer satisfaction.


from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.newspaper4k import Newspaper4kTools



autonomous_startup_team = Team(
    name="Autonomous Startup Team",
    mode="coordinator",
    model=OpenAIChat("gpt-4o"),
    members=[],
)


autonomous_startup_team.print_response(
    message="?",
    stream=True,
    stream_intermediate_steps=True,
)
