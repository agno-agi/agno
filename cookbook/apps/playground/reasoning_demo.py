"""Run `pip install openai exa_py duckduckgo-search yfinance pypdf sqlalchemy 'fastapi[standard]' youtube-transcript-api python-docx agno` to install dependencies."""

import asyncio
from textwrap import dedent

from agno.agent import Agent
from agno.knowledge.url import UrlKnowledge
from agno.models.openai import OpenAIChat
from agno.playground import Playground, serve_playground_app
from agno.storage.sqlite import SqliteStorage
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.knowledge import KnowledgeTools
from agno.tools.reasoning import ReasoningTools
from agno.tools.thinking import ThinkingTools
from agno.tools.yfinance import YFinanceTools
from agno.vectordb.lancedb import LanceDb, SearchType

agent_storage_file: str = "tmp/agents.db"
image_agent_storage_file: str = "tmp/image_agent.db"

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"


finance_agent = Agent(
    name="Finance Agent",
    role="Get financial data",
    agent_id="finance-agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        YFinanceTools(
            stock_price=True,
            analyst_recommendations=True,
            company_info=True,
            company_news=True,
        )
    ],
    instructions=["Always use tables to display data"],
    storage=SqliteStorage(
        table_name="finance_agent", db_file=agent_storage_file, auto_upgrade_schema=True
    ),
    add_history_to_messages=True,
    num_history_responses=5,
    add_datetime_to_instructions=True,
    markdown=True,
)

cot_agent = Agent(
    name="Chain-of-Thought Agent",
    role="Answer basic questions",
    agent_id="cot-agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    storage=SqliteStorage(
        table_name="cot_agent", db_file=agent_storage_file, auto_upgrade_schema=True
    ),
    add_history_to_messages=True,
    num_history_responses=3,
    add_datetime_to_instructions=True,
    markdown=True,
    reasoning=True,
)

reasoning_model_agent = Agent(
    name="Reasoning Model Agent",
    role="Reasoning about Math",
    agent_id="reasoning-model-agent",
    model=OpenAIChat(id="gpt-4o"),
    reasoning_model=OpenAIChat(id="o3-mini"),
    instructions=["You are a reasoning agent that can reason about math."],
    show_tool_calls=True,
    markdown=True,
    debug_mode=True,
    storage=SqliteStorage(
        table_name="reasoning_model_agent",
        db_file=agent_storage_file,
        auto_upgrade_schema=True,
    ),
)

reasoning_tool_agent = Agent(
    name="Reasoning Tool Agent",
    role="Answer basic questions",
    agent_id="reasoning-tool-agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    storage=SqliteStorage(
        table_name="reasoning_tool_agent",
        db_file=agent_storage_file,
        auto_upgrade_schema=True,
    ),
    add_history_to_messages=True,
    num_history_responses=3,
    add_datetime_to_instructions=True,
    markdown=True,
    tools=[ReasoningTools()],
)


web_agent = Agent(
    name="Web Search Agent",
    role="Handle web search requests",
    model=OpenAIChat(id="gpt-4o-mini"),
    agent_id="web_agent",
    tools=[DuckDuckGoTools()],
    instructions="Always include sources",
    add_datetime_to_instructions=True,
    storage=SqliteStorage(
        table_name="web_agent",
        db_file=agent_storage_file,
        auto_upgrade_schema=True,
    ),
)

thinking_tool_agent = Agent(
    name="Thinking Tool Agent",
    agent_id="thinking_tool_agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[ThinkingTools(add_instructions=True), YFinanceTools(enable_all=True)],
    instructions=dedent("""\
        You are a seasoned Wall Street analyst with deep expertise in market analysis! 📊

        Follow these steps for comprehensive financial analysis:
        1. Market Overview
           - Latest stock price
           - 52-week high and low
        2. Financial Deep Dive
           - Key metrics (P/E, Market Cap, EPS)
        3. Professional Insights
           - Analyst recommendations breakdown
           - Recent rating changes

        4. Market Context
           - Industry trends and positioning
           - Competitive analysis
           - Market sentiment indicators

        Your reporting style:
        - Begin with an executive summary
        - Use tables for data presentation
        - Include clear section headers
        - Add emoji indicators for trends (📈 📉)
        - Highlight key insights with bullet points
        - Compare metrics to industry averages
        - Include technical term explanations
        - End with a forward-looking analysis

        Risk Disclosure:
        - Always highlight potential risk factors
        - Note market uncertainties
        - Mention relevant regulatory concerns\
    """),
    add_datetime_to_instructions=True,
    show_tool_calls=True,
    markdown=True,
    stream_intermediate_steps=True,
    storage=SqliteStorage(
        table_name="thinking_tool_agent",
        db_file=agent_storage_file,
        auto_upgrade_schema=True,
    ),
)


agno_docs = UrlKnowledge(
    urls=["https://www.paulgraham.com/read.html"],
    # Use LanceDB as the vector database and store embeddings in the `agno_docs` table
    vector_db=LanceDb(
        uri="tmp/lancedb",
        table_name="agno_docs",
        search_type=SearchType.hybrid,
    ),
)

knowledge_tools = KnowledgeTools(
    knowledge=agno_docs,
    think=True,
    search=True,
    analyze=True,
    add_few_shot=True,
)
knowledge_agent = Agent(
    agent_id="knowledge_agent",
    name="Knowledge Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[knowledge_tools],
    show_tool_calls=True,
    markdown=True,
    storage=SqliteStorage(
        table_name="knowledge_agent",
        db_file=agent_storage_file,
        auto_upgrade_schema=True,
    ),
)

reasoning_finance_team = Team(
    name="Reasoning Finance Team",
    mode="coordinate",
    model=OpenAIChat(id="gpt-4o"),
    members=[
        web_agent,
        finance_agent,
    ],
    # reasoning=True,
    tools=[ReasoningTools(add_instructions=True)],
    # uncomment it to use knowledge tools
    # tools=[knowledge_tools],
    team_id="reasoning_finance_team",
    debug_mode=True,
    instructions=[
        "Only output the final answer, no other text.",
        "Use tables to display data",
    ],
    markdown=True,
    show_members_responses=True,
    enable_agentic_context=True,
    add_datetime_to_instructions=True,
    success_criteria="The team has successfully completed the task.",
    storage=SqliteStorage(
        table_name="reasoning_finance_team",
        db_file=agent_storage_file,
        auto_upgrade_schema=True,
    ),
)


app = Playground(
    agents=[
        cot_agent,
        reasoning_tool_agent,
        reasoning_model_agent,
        knowledge_agent,
        thinking_tool_agent,
    ],
    teams=[reasoning_finance_team],
).get_app()

if __name__ == "__main__":
    asyncio.run(agno_docs.aload(recreate=True))
    serve_playground_app("reasoning_demo:app", reload=True)


# reasoning_tool_agent
# Solve this logic puzzle: A man has to take a fox, a chicken, and a sack of grain across a river.
# The boat is only big enough for the man and one item. If left unattended together,
# the fox will eat the chicken, and the chicken will eat the grain. How can the man get everything across safely?


# knowledge_agent prompt
# What does Paul Graham explain here with respect to need to read?
