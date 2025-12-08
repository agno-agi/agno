from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.db.postgres import PostgresDb
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.builder import BuilderConfig
from agno.tools.arxiv import ArxivTools
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.file import FileTools
from agno.tools.wikipedia import WikipediaTools
from agno.tools.yfinance import YFinanceTools

# Tools available for the builder
tools = [
    DuckDuckGoTools(),
    YFinanceTools(),
    FileTools(),
    WikipediaTools(),
    ArxivTools(),
]

# Models available for the builder
models = [
    OpenAIChat(id="gpt-4o"),
    OpenAIChat(id="gpt-4o-mini"),
    Gemini(id="gemini-1.5-flash"),
    Claude(id="claude-3-5-sonnet-20240620"),
]

# Databases available for the builder
databases = [
    SqliteDb(db_url="sqlite:///tmp/agent_os.db"),
    PostgresDb(
        db_url="postgresql://postgres:postgres@localhost:5432/agent_os",
    ),
    InMemoryDb(),
]

# Create the BuilderConfiguration
builder_config = BuilderConfig(
    tools=tools,
    models=models,
    databases=databases,
)

# Initialize AgentOS with the builder configuration
agent_os = AgentOS(
    builder=builder_config,
    # Need to pass an agent for instantiation - shouldn't be necessary once we persist agent configurations
    agents=[Agent(model=OpenAIChat(id="gpt-4o-mini"), description="Welcome Agent")],
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="01_agent_builder:app")
