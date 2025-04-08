"""Readme Examples
Run `pip install openai duckduckgo-search yfinance lancedb tantivy pypdf agno` to install dependencies."""

from agno.agent import Agent
from agno.embedder.openai import OpenAIEmbedder
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools
from agno.vectordb.lancedb import LanceDb, SearchType

# Level 0: Agents with no tools (basic inference tasks).
level_0_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    description="You are an enthusiastic news reporter with a flair for storytelling!",
    markdown=True,
)
level_0_agent.print_response(
    "Tell me about a breaking news story from New York.", stream=True
)

# Level 1: Agents with tools for autonomous task execution.
level_1_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    description="You are an enthusiastic news reporter with a flair for storytelling!",
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
)
level_1_agent.print_response(
    "Tell me about a breaking news story from New York.", stream=True
)

# Level 2: Agents with knowledge, combining memory and reasoning.
level_2_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    description="You are a Thai cuisine expert!",
    instructions=[
        "Search your knowledge base for Thai recipes.",
        "If the question is better suited for the web, search the web to fill in gaps.",
        "Prefer the information in your knowledge base over the web results.",
    ],
    knowledge=PDFUrlKnowledgeBase(
        urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
        vector_db=LanceDb(
            uri="tmp/lancedb",
            table_name="recipes",
            search_type=SearchType.hybrid,
            embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        ),
    ),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
)

# Comment out after first run
# if level_2_agent.knowledge is not None:
#     level_2_agent.knowledge.load()
level_2_agent.print_response(
    "How do I make chicken and galangal in coconut milk soup", stream=True
)
level_2_agent.print_response("What is the history of Thai curry?", stream=True)

# Level 3: Teams of agents collaborating on complex workflows.
web_agent = Agent(
    name="Web Agent",
    role="Search the web for information",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    instructions="Always include sources",
    show_tool_calls=True,
    markdown=True,
)

finance_agent = Agent(
    name="Finance Agent",
    role="Get financial data",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        YFinanceTools(stock_price=True, analyst_recommendations=True, company_info=True)
    ],
    instructions="Use tables to display data",
    show_tool_calls=True,
    markdown=True,
)

level_3_agent_team = Team(
    members=[web_agent, finance_agent],
    model=OpenAIChat(id="gpt-4o"),
    mode="coordinate",
    success_criteria="A comprehensive financial news report with clear sections and data-driven insights.",
    instructions=["Always include sources", "Use tables to display data"],
    show_tool_calls=True,
    markdown=True,
)
level_3_agent_team.print_response(
    "What's the market outlook and financial performance of AI semiconductor companies?",
    stream=True,
)
