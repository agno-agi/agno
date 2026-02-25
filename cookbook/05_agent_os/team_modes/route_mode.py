"""
Route Mode: Intelligent Expertise-Based Routing
================================================

Demonstrates the route pattern where the team lead routes requests to a single
specialist member and returns their response directly without synthesis.

Inspired by Claude Cowork's department-specific plugins and intelligent routing
to specialized agents (HR, Design, Engineering, Finance, etc.).

Key patterns:
- Team lead makes routing decision based on request analysis
- Single member handles the request (not broadcast to all)
- Response returned directly without leader synthesis
- Efficient for domain-specific queries with clear expert mapping

Run with: .venvs/demo/bin/python cookbook/05_agent_os/team_modes/route_mode.py
Access at: http://localhost:7777
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team import Team, TeamMode
from agno.tools.websearch import WebSearchTools
from agno.tools.yfinance import YFinanceTools

# ---------------------------------------------------------------------------
# Database Setup
# ---------------------------------------------------------------------------
db = PostgresDb(
    id="team-modes-db",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

# ---------------------------------------------------------------------------
# Department Specialists (Inspired by Cowork's Role-Specific Plugins)
# ---------------------------------------------------------------------------

hr_specialist = Agent(
    name="HR Specialist",
    id="hr-specialist",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    role="Handle HR policies, benefits, leave requests, and employee relations",
    instructions=[
        "You are an HR specialist with expertise in employee policies.",
        "For leave requests: explain the process, requirements, and approval flow.",
        "For benefits questions: detail coverage, enrollment, and eligibility.",
        "For policy questions: cite specific policy sections when possible.",
        "For sensitive matters: recommend scheduling a private consultation.",
        "Always maintain confidentiality and professionalism.",
    ],
    update_memory_on_run=True,
    markdown=True,
)

engineering_lead = Agent(
    name="Engineering Lead",
    id="engineering-lead",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    role="Handle technical architecture, code reviews, and engineering processes",
    instructions=[
        "You are a senior engineering lead with expertise in software architecture.",
        "For architecture questions: explain tradeoffs and provide recommendations.",
        "For process questions: describe our SDLC, CI/CD, and review processes.",
        "For technical decisions: consider scalability, maintainability, and cost.",
        "Provide code examples when helpful.",
        "Encourage best practices and mention relevant internal documentation.",
    ],
    update_memory_on_run=True,
    markdown=True,
)

finance_analyst = Agent(
    name="Finance Analyst",
    id="finance-analyst",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    role="Handle financial analysis, market data, and investment queries",
    tools=[YFinanceTools(stock_price=True, analyst_recommendations=True, company_info=True)],
    instructions=[
        "You are a financial analyst with access to real-time market data.",
        "For stock queries: provide current price, key metrics, and analyst views.",
        "For company analysis: include fundamentals, recent news, and outlook.",
        "For portfolio questions: consider risk, diversification, and objectives.",
        "Always include relevant disclaimers for investment-related advice.",
        "Use data to support your analysis.",
    ],
    update_memory_on_run=True,
    markdown=True,
)

research_analyst = Agent(
    name="Research Analyst",
    id="research-analyst",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    role="Handle research queries, competitive analysis, and market intelligence",
    tools=[WebSearchTools()],
    instructions=[
        "You are a research analyst with expertise in market intelligence.",
        "For competitor analysis: provide structured comparisons with sources.",
        "For market research: include trends, sizing, and key players.",
        "For industry questions: explain dynamics, regulations, and outlook.",
        "Always cite sources and distinguish facts from analysis.",
        "Highlight confidence level and gaps in available information.",
    ],
    update_memory_on_run=True,
    markdown=True,
)

legal_counsel = Agent(
    name="Legal Counsel",
    id="legal-counsel",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    role="Handle legal questions, compliance, and contract review",
    instructions=[
        "You are in-house legal counsel with expertise in corporate law.",
        "For contract questions: explain terms, risks, and negotiation points.",
        "For compliance questions: describe requirements and our obligations.",
        "For legal risks: assess exposure and recommend mitigation.",
        "Always recommend formal legal review for binding decisions.",
        "Flag matters that require external counsel involvement.",
    ],
    update_memory_on_run=True,
    markdown=True,
)

it_support = Agent(
    name="IT Support",
    id="it-support",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    role="Handle IT issues, access requests, and technical troubleshooting",
    instructions=[
        "You are IT support with expertise in enterprise systems.",
        "For access requests: explain the process and approval requirements.",
        "For troubleshooting: provide step-by-step diagnostic procedures.",
        "For software requests: explain our approved software policy.",
        "For security issues: escalate immediately and provide interim steps.",
        "Always log tickets for tracking and SLA compliance.",
    ],
    update_memory_on_run=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Enterprise Help Desk (Route Mode)
# ---------------------------------------------------------------------------

enterprise_helpdesk = Team(
    name="Enterprise Help Desk",
    id="enterprise-helpdesk",
    description="Intelligent routing to department specialists for enterprise queries",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    members=[
        hr_specialist,
        engineering_lead,
        finance_analyst,
        research_analyst,
        legal_counsel,
        it_support,
    ],
    mode=TeamMode.route,
    instructions=[
        "You are an intelligent enterprise help desk router.",
        "",
        "Routing Protocol:",
        "1. ANALYZE: Parse the user's request to identify the domain",
        "2. CLASSIFY: Map to the most appropriate specialist",
        "3. ROUTE: Forward to the selected specialist with full context",
        "",
        "Routing Rules:",
        "- HR queries (leave, benefits, policies, hiring) -> HR Specialist",
        "- Technical questions (architecture, code, CI/CD) -> Engineering Lead",
        "- Financial queries (stocks, markets, budgets) -> Finance Analyst",
        "- Research requests (competitors, markets, trends) -> Research Analyst",
        "- Legal questions (contracts, compliance, risk) -> Legal Counsel",
        "- IT issues (access, software, troubleshooting) -> IT Support",
        "",
        "Edge Cases:",
        "- If query spans multiple domains, route to the PRIMARY domain",
        "- If unclear, ask ONE clarifying question before routing",
        "- For greetings/small talk, respond directly without routing",
        "",
        "The specialist's response is returned directly to the user.",
    ],
    markdown=True,
    show_members_responses=True,
    update_memory_on_run=True,
)

# ---------------------------------------------------------------------------
# AgentOS Setup
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    description="Enterprise Help Desk with Route Mode - Intelligent routing to department specialists",
    agents=[hr_specialist, engineering_lead, finance_analyst, research_analyst, legal_counsel, it_support],
    teams=[enterprise_helpdesk],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run your AgentOS.

    Access the API at: http://localhost:7777
    View configuration at: http://localhost:7777/config

    Example queries to try:
    - "How do I request PTO for next week?"
    - "What's the current stock price of NVDA and analyst consensus?"
    - "Can you explain our microservices architecture?"
    - "I need competitor analysis for our Q1 planning"
    """
    agent_os.serve(app="route_mode:app", reload=True)
