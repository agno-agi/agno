"""
This example demonstrates a team of agents that can answer a variety of questions.

The team uses reasoning tools to reason about the questions and delegate to the appropriate agent.

The team consists of:
- A web agent that can search the web for information
- A finance agent that can get financial data
- A writer agent that can write content
- A calculator agent that can calculate
- A FastAPI assistant that can explain how to write FastAPI code
- A code execution agent that can execute code in a secure E2B sandbox
"""
import asyncio
from textwrap import dedent

from agno.agent import Agent
from agno.document.reader.firecrawl_reader import FirecrawlReader
from agno.embedder.google import GeminiEmbedder
from agno.knowledge.firecrawl import FireCrawlKnowledgeBase
from agno.knowledge.website import WebsiteKnowledgeBase
from agno.models.anthropic import Claude
from agno.storage.sqlite import SqliteStorage
from agno.team.team import Team
from agno.tools.calculator import CalculatorTools
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.e2b import E2BTools
from agno.tools.exa import ExaTools
from agno.tools.knowledge import KnowledgeTools
from agno.tools.reasoning import ReasoningTools
from agno.tools.yfinance import YFinanceTools
from agno.vectordb.lancedb.lance_db import LanceDb
from agno.vectordb.search import SearchType

# Agent that can search the web for information
web_agent = Agent(
    name="Web Agent",
    role="Search the web for information",
    model=Claude(id="claude-3-5-sonnet-latest"),
    tools=[ExaTools(cache_results=True)],
    instructions=["Always include sources"],
)

reddit_researcher = Agent(
    name="Reddit Researcher",
    role="Research a topic on Reddit",
    model=Claude(id="claude-3-5-sonnet-latest"),
    tools=[DuckDuckGoTools(cache_results=True)],
    add_name_to_instructions=True,
    instructions=dedent("""
    You are a Reddit researcher.
    You will be given a topic to research on Reddit.
    You will need to find the most relevant information on Reddit.
    """),
)

# Agent that can get financial data
finance_agent = Agent(
    name="Finance Agent",
    role="Get financial data",
    model=Claude(id="claude-3-5-sonnet-latest"),
    tools=[
        YFinanceTools(stock_price=True, 
                      analyst_recommendations=True, 
                      company_info=True,
                      company_news=True)
    ],
    instructions=["Use tables to display data"],
)

# Writer agent that can write content
writer_agent = Agent(
    name="Write Agent",
    role="Write content",
    model=Claude(id="claude-3-5-sonnet-latest"),
    description="You are an AI agent that can write content.",
    instructions=[
        "You are a versatile writer who can create content on any topic.",
        "When given a topic, write engaging and informative content in the requested format and style.",
        "If you receive mathematical expressions or calculations from the calculator agent, convert them into clear written text.",
        "Ensure your writing is clear, accurate and tailored to the specific request.",
        "Maintain a natural, engaging tone while being factually precise.",
        "Write something that would be good enough to be published in a newspaper like the New York Times.",
    ],
)

# Calculator agent that can calculate
calculator_agent = Agent(
    name="Calculator Agent",
    model=Claude(id="claude-3-5-sonnet-latest"),
    role="Calculate",
    tools=[
        CalculatorTools(
            add=True,
            subtract=True,
            multiply=True,
            divide=True,
            exponentiate=True,
            factorial=True,
            is_prime=True,
            square_root=True,
        )
    ],
    show_tool_calls=True,
    markdown=True,
)

# FastAPI assistant that can explain how to write FastAPI code
fastapi_knowledge = WebsiteKnowledgeBase(
    urls=["https://fastapi.tiangolo.com/"],
    max_links=20,
    vector_db=LanceDb(
            uri="tmp/lancedb",
            table_name="fastapi_assist_knowledge",
            search_type=SearchType.hybrid,
            embedder=GeminiEmbedder(),
        ),
    )
fastapi_assist = Agent(
    name="FastAPI Assist",
    role="Explain how to write FastAPI code",
    model=Claude(id="claude-3-5-sonnet-latest"),
    description="You help answer questions about the FastAPI framework.",
    instructions="Search your knowledge before answering the question.",
    tools=[
        KnowledgeTools(knowledge=fastapi_knowledge, add_instructions=True, add_few_shot=True),
    ],
    storage=SqliteStorage(table_name="agno_assist_sessions", db_file="tmp/agents.db"),
    add_history_to_messages=True,
    add_datetime_to_instructions=True,
    markdown=True,
)


code_execution_agent = Agent(
    name="Code Execution Sandbox",
    agent_id="e2b-sandbox",
    model=Claude(id="claude-3-5-sonnet-latest"),
    tools=[E2BTools()],
    markdown=True,
    show_tool_calls=True,
    instructions=[
        "You are an expert at writing and validating Python code using a secure E2B sandbox environment.",
        "Your primary purpose is to:",
        "1. Write clear, efficient Python code based on user requests",
        "2. Execute and verify the code in the E2B sandbox",
        "3. Share the complete code with the user, as this is the main use case",
        "4. Provide thorough explanations of how the code works",
        "",
    ],
)

agent_team = Team(
    name="Multi-Purpose Team",
    mode="coordinate",
    model=Claude(id="claude-3-7-sonnet-latest"),
    tools=[
        ReasoningTools(add_instructions=True, add_few_shot=True),
    ],
    members=[
        web_agent,
        finance_agent,
        writer_agent,
        calculator_agent,
        fastapi_assist,
        code_execution_agent,
    ],
    instructions=[
        "You are a team of agents that can answer a variety of questions.",
        "You can use your member agents to answer the questions.",
        "You can also answer directly, you don't HAVE to forward the question to a member agent.",
        "Reason about more complex questions before delegating to a member agent.",
        "If the user is only being conversational, don't use any tools, just answer directly.",
    ],
    markdown=True,
    show_members_responses=True,
)

if __name__ == "__main__":
    # Load the knowledge base (comment out after first run)
    asyncio.run(fastapi_knowledge.aload())
    
    asyncio.run(agent_team.aprint_response("Hi! What are you capable of doing?"))
    
    # # FastAPI endpoint
    # asyncio.run(agent_team.aprint_response("What is the right way to implement a simple FastAPI endpoint with middleware? Create a minimal example for me and test it to ensure it won't immediately crash."))
    
    # # Reddit research
    # asyncio.run(agent_team.aprint_response("""What should I be investing in right now? 
    #                                        Find some popular subreddits and do some reseach of your own. 
    #                                        Write a detailed report about your findings that could be given to a financial advisor."""))