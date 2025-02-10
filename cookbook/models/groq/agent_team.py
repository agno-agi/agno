from agno.agent import Agent
from agno.models.groq import Groq
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

agent_team = Agent(
    team=[web_agent, finance_agent],
    model=Groq(
        id="llama-3.3-70b-versatile"
    ),  # You can use a different model for the team leader agent
    instructions=["Always include sources", "Use tables to display data"],
    show_tool_calls=True,  # Comment to hide transfer of tasks between agents
    markdown=True,
)

# Give the team a task
agent_team.print_response(
    "Summarize the latest news about Nvidia and share its stock price?", stream=True
)
