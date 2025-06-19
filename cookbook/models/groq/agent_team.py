from agno.agent import Agent
from agno.models.groq import Groq
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools

web_agent = Agent(
    name="Web Agent",
    role="Search the web for information",
    model=Groq(id="llama-3.3-70b-versatile"),
    tools=[DuckDuckGoTools()],
    instructions="Always include sources",
    markdown=True,
)

finance_agent = Agent(
    name="Finance Agent",
    role="Get financial data",
    model=Groq(id="llama-3.3-70b-versatile"),
    tools=[
        YFinanceTools(stock_price=True, analyst_recommendations=True, company_info=True)
    ],
    instructions="Use tables to display data",
    markdown=True,
)

agent_team = Team(
    members=[web_agent, finance_agent],
    mode="coordinate",
    model=Groq(
        id="llama-3.3-70b-versatile"
    ),  # You can use a different model for the team leader agent
    success_criteria="The team has successfully completed the task",
    instructions=["Always include sources", "Use tables to display data"],
    show_tool_calls=True,  # Comment to hide transfer of tasks between agents
    markdown=True,
    enable_agentic_context=True,
    debug_mode=True,
    show_members_responses=False,  # Comment to hide responses from team members
)

# Give the team a task
agent_team.print_response(
    message="Summarize the latest news about Nvidia and share its stock price?",
    stream=True,
)
