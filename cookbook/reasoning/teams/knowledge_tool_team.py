from textwrap import dedent

from agno.agent import Agent
from agno.knowledge.url import UrlKnowledge
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.knowledge import KnowledgeTools
from agno.tools.reasoning import ReasoningTools
from agno.tools.yfinance import YFinanceTools
from agno.vectordb.lancedb import LanceDb, SearchType

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
    add_datetime_to_instructions=True,
)

team_leader = Team(
    name="Reasoning Finance Team",
    mode="coordinate",
    model=OpenAIChat(id="gpt-4o"),
    members=[
        web_agent,
        finance_agent,
    ],
    tools=[knowledge_tools],
    instructions=[
        "Only output the final answer, no other text.",
        "Use tables to display data",
    ],
    markdown=True,
    show_members_responses=True,
    enable_agentic_context=True,
    add_datetime_to_instructions=True,
    success_criteria="The team has successfully completed the task.",
    debug_mode=True,
)


def run_team(task: str):
    # Comment out after first run
    agno_docs.load(recreate=True)
    team_leader.print_response(
        task,
        stream=True,
        stream_intermediate_steps=True,
        show_full_reasoning=True,
    )


if __name__ == "__main__":
    run_team("What does Paul Graham talk about the need to read in this essay?")
