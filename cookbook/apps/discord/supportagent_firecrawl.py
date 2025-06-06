
from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.reasoning import ReasoningTools
from agno.app.discord.client import DiscordClient
from agno.tools.firecrawl import FirecrawlTools

docs_agent = Agent(
    model=Claude(id="claude-3-7-sonnet-latest"),
    # Agentic RAG is enabled by default when `knowledge` is provided to the Agent.
    # search_knowledge=True gives the Agent the ability to search on demand
    # search_knowledge is True by default
    search_knowledge=True,
    tools=[ReasoningTools(add_instructions=True),FirecrawlTools(scrape=False, crawl=True, search=True, poll_interval=2)],
    instructions=[
        "You are an user support agent for Agno, use firecrawl tool to browse through https://docs.agno.com/ and answer users"
        "Include sources in your response.",
        "Always search your knowledge before answering the question.",
    ],
    add_history_to_messages=True,
    num_history_responses=3,
    add_datetime_to_instructions=True,
    markdown=True,
    debug_mode=True
)

DiscordClient(docs_agent)