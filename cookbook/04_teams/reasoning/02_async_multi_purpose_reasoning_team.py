"""
This example demonstrates an async multi-purpose reasoning team.

The team uses reasoning tools to analyze questions and delegate to appropriate
specialist agents asynchronously, showcasing coordination and intelligent task routing.
"""

import asyncio
from pathlib import Path

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.calculator import CalculatorTools
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.e2b import E2BTools
from agno.tools.knowledge import KnowledgeTools
from agno.tools.pubmed import PubmedTools
from agno.tools.reasoning import ReasoningTools
from agno.tools.yfinance import YFinanceTools
from agno.vectordb.lancedb.lance_db import LanceDb
from agno.vectordb.search import SearchType

cwd = Path(__file__).parent.resolve()

# Web search agent
web_agent = Agent(
    name="Web Agent",
    role="Search the web for information",
    model=Claude(id="claude-3-5-sonnet-latest"),
    tools=[DuckDuckGoTools(cache_results=True)],
    instructions=["Always include sources"],
)

# Financial data agent
finance_agent = Agent(
    name="Finance Agent",
    model=Claude(id="claude-3-5-sonnet-latest"),
    role="Get financial data",
    tools=[YFinanceTools()],
    instructions=[
        "You are a finance agent that can get financial data about stocks, companies, and the economy.",
        "Always use real-time data when possible.",
    ],
)

# Medical research agent
medical_agent = Agent(
    name="Medical Agent",
    model=Claude(id="claude-3-5-sonnet-latest"),
    role="Medical researcher",
    tools=[PubmedTools()],
    instructions=[
        "You are a medical agent that can answer questions about medical topics.",
        "Always search for recent medical literature and evidence.",
    ],
)

# Calculator agent
calculator_agent = Agent(
    name="Calculator Agent",
    model=Claude(id="claude-3-5-sonnet-latest"),
    role="Perform mathematical calculations",
    tools=[CalculatorTools()],
    instructions=[
        "Perform accurate mathematical calculations.",
        "Show your work step by step.",
    ],
)

# Agno documentation knowledge base
agno_assist_knowledge = Knowledge(
    vector_db=LanceDb(
        uri="tmp/lancedb",
        table_name="agno_assist_knowledge",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# Agno framework assistant
agno_assist = Agent(
    name="Agno Assist",
    role="Help with Agno framework questions and code",
    model=OpenAIChat(id="o3-mini"),
    instructions="Search your knowledge before answering. Help write working Agno code.",
    tools=[
        KnowledgeTools(
            knowledge=agno_assist_knowledge, add_instructions=True, add_few_shot=True
        ),
    ],
    add_history_to_context=True,
    add_datetime_to_context=True,
)

# Code execution agent
code_agent = Agent(
    name="Code Agent",
    model=Claude(id="claude-3-5-sonnet-latest"),
    role="Execute and test code",
    tools=[E2BTools()],
    instructions=[
        "Execute code safely in the sandbox environment.",
        "Test code thoroughly before providing results.",
        "Provide clear explanations of code execution.",
    ],
)

# Create multi-purpose reasoning team
agent_team = Team(
    name="Multi-Purpose Agent Team",
    model=Claude(id="claude-3-5-sonnet-latest"),
    tools=[ReasoningTools()],  # Enable reasoning capabilities
    members=[
        web_agent,
        finance_agent,
        medical_agent,
        calculator_agent,
        agno_assist,
        code_agent,
    ],
    instructions=[
        "You are a team of agents that can answer a variety of questions.",
        "Use reasoning tools to analyze questions before delegating.",
        "You can answer directly or forward to appropriate specialist agents.",
        "For complex questions, reason about the best approach first.",
        "If the user is just being conversational, respond directly without tools.",
    ],
    markdown=True,
    show_members_responses=True,
    share_member_interactions=True,
)


async def main():
    """Main async function to demonstrate different team capabilities."""

    # Add Agno documentation content
    await agno_assist_knowledge.add_contents_async(
        url="https://docs.agno.com/llms-full.txt"
    )

    # Example interactions:

    # 1. General capability query
    await agent_team.aprint_response(input="Hi! What are you capable of doing?")

    # 2. Technical code question
    # await agent_team.aprint_response(dedent("""
    #     Create a minimal Agno Agent that searches Hacker News for articles.
    #     Test it locally and save it as './python/hacker_news_agent.py'.
    #     Use real Agno documentation, don't mock anything.
    # """), stream=True)

    # 3. Financial research
    # await agent_team.aprint_response(dedent("""
    #     What should I be investing in right now?
    #     Research current market trends and write a detailed report
    #     suitable for a financial advisor.
    # """), stream=True)

    # 4. Medical analysis (using external medical history file)
    # txt_path = Path(__file__).parent.resolve() / "medical_history.txt"
    # if txt_path.exists():
    #     loaded_txt = open(txt_path, "r").read()
    #     await agent_team.aprint_response(
    #         f"Analyze this medical information and suggest a likely diagnosis:\n{loaded_txt}",
    #         stream=True,
    #     )


if __name__ == "__main__":
    asyncio.run(main())
