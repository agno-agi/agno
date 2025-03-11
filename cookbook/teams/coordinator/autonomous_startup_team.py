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
from agno.tools.yfinance import YFinanceTools
from agno.tools.exa import ExaTools
from agno.knowledge.pdf import PDFKnowledgeBase

knowledge_base = PDFKnowledgeBase(
    path="docs/autonomous_startup_team.pdf",
)

product_manager_agent = Agent(
    name="Product Manager Agent",
    role="Product Manager",
    model=OpenAIChat("gpt-4o"),
    instructions=[
        "You are the Product Manager of a startup. You are responsible for defining the product roadmap, gathering user feedback, and refining features.",
    ],
    add_datetime_to_instructions=True,
    markdown=True,
    tools=[],
)

market_research_agent = Agent(
    name="Market Research Agent",
    role="Market Research",
    model=OpenAIChat("gpt-4o"),
    tools=[DuckDuckGoTools(), ExaTools()],
    instructions=[
        "You are the Market Research Agent of a startup. You are responsible for analyzing industry trends, competitors, and customer demands.",
    ],
    add_datetime_to_instructions=True,
    markdown=True,
)

sales_agent = Agent(
    name="Sales Agent",
    role="Sales",
    model=OpenAIChat("gpt-4o"),
    tools=[DuckDuckGoTools(), ExaTools()],
    instructions=[
        "You are the Sales Agent of a startup. You are responsible for identifying leads, negotiating deals, and tracking conversions.",
    ],
    add_datetime_to_instructions=True,
    markdown=True,
)


financial_analyst_agent = Agent(
    name="Financial Analyst Agent",
    role="Financial Analyst",
    model=OpenAIChat("gpt-4o"),
    tools=[YFinanceTools()],
    instructions=[
        "You are the Financial Analyst of a startup. You are responsible for handling revenue projections, pricing strategies, and investor reports.",
    ],
    add_datetime_to_instructions=True,
    markdown=True,
)


autonomous_startup_team = Team(
    name="CEO Agent",
    mode="coordinator",
    model=OpenAIChat("gpt-4o"),
    instructions=[
        "You are the CEO of a startup. You are responsible for setting the vision, prioritizing tasks, and making strategic decisions.",
    ],
    add_datetime_to_instructions=True,
    markdown=True,
    members=[product_manager_agent, market_research_agent, sales_agent, financial_analyst_agent],
)


autonomous_startup_team.print_response(
    message="I want to start a startup that sells AI agents to businesses. What is the best way to do this?",
    stream=True,
    stream_intermediate_steps=True,
)
