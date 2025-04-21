"""Run `pip install openai exa_py duckduckgo-search yfinance pypdf sqlalchemy 'fastapi[standard]' youtube-transcript-api python-docx agno` to install dependencies."""

import asyncio
from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.playground import Playground, serve_playground_app
from agno.storage.sqlite import SqliteStorage
from agno.team import Team
from agno.tools.reasoning import ReasoningTools
from agno.tools.thinking import ThinkingTools
from agno.tools.yfinance import YFinanceTools
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.embedder.openai import OpenAIEmbedder
from agno.knowledge.url import UrlKnowledge
from agno.tools.knowledge import KnowledgeTools
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
    name="COT Agent",
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

native_model_agent = Agent(
    model=OpenAIChat(id="o3-mini", reasoning_effort="high"),
    name="Native Model Agent",
    agent_id="native_model_agent",
    tools=[
        YFinanceTools(
            stock_price=True,
            analyst_recommendations=True,
            company_info=True,
            company_news=True,
        )
    ],
    instructions="Use tables to display data.",
    show_tool_calls=True,
    markdown=True,
    storage=SqliteStorage(
        table_name="native_model_agent",
        db_file=agent_storage_file,
        auto_upgrade_schema=True,
    ),
)

claude_thinking_agent = Agent(
    name="Claude Thinking Agent",
    agent_id="claude_thinking_agent",
    model=Claude(
        id="claude-3-7-sonnet-20250219",
        max_tokens=2048,
        thinking={"type": "enabled", "budget_tokens": 1024},
    ),
    markdown=True,
    storage=SqliteStorage(
        table_name="claude_thinking_agent",
        db_file=agent_storage_file,
        auto_upgrade_schema=True,
    ),
)


web_agent = Agent(
    name="Web Search Agent",
    role="Handle web search requests",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    instructions="Always include sources",
    add_datetime_to_instructions=True,
)

finance_agent = Agent(
    name="Finance Agent",
    role="Handle financial data requests",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[
        YFinanceTools(stock_price=True, analyst_recommendations=True, company_info=True)
    ],
    instructions=[
        "You are a financial data specialist. Provide concise and accurate data.",
        "Use tables to display stock prices, fundamentals (P/E, Market Cap), and recommendations.",
        "Clearly state the company name and ticker symbol.",
        "Briefly summarize recent company-specific news if available.",
        "Focus on delivering the requested financial data points clearly.",
    ],
    add_datetime_to_instructions=True,
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
)

reasoning_finance_team = Team(
    name="Reasoning Finance Team",
    mode="coordinate",
    model=Claude(id="claude-3-7-sonnet-latest"),
    members=[
        web_agent,
        finance_agent,
    ],
    reasoning=True,
    # uncomment it to use knowledge tools
    # tools=[knowledge_tools],
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
        native_model_agent,
        claude_thinking_agent,
        knowledge_agent,
    ],
    teams=[reasoning_finance_team],
).get_app()

if __name__ == "__main__":
    asyncio.run(agno_docs.aload(recreate=True))
    serve_playground_app("reasoning_demo:app", reload=True)


#reasoning_tool_agent
# Solve this logic puzzle: A man has to take a fox, a chicken, and a sack of grain across a river.
# The boat is only big enough for the man and one item. If left unattended together, 
# the fox will eat the chicken, and the chicken will eat the grain. How can the man get everything across safely?


# knowledge_agent prompt
# How do I build multi-agent teams with Agno?

#claude_thinking_agent prompt
#Analyse tesal stocks

