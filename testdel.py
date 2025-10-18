import os

from agno.tools.tavily import TavilyTools
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.db.sqlite import SqliteDb

api_key = os.getenv("TAVILY_API_KEY")

if not api_key:
    print("Error: TAVILY_API_KEY environment variable not set")
    exit(1)

print("=" * 80)
print("TESTING TAVILY WITH AGENTOS")
print("=" * 80)

# Create database for the agent
db = SqliteDb(db_file="tmp/tavily_test.db")

# Create agent with TavilyTools for AgentOS
tavily_agent = Agent(
    name="TavilyExtractor",
    model=OpenAIChat(id="gpt-4o"),
    db=db,  # Configure database on the agent
    tools=[TavilyTools(
        enable_search=True,  # Enable both search and extract
        enable_extract=True,
        search_depth="basic",
        extract_depth="basic",
        extract_format="markdown",
    )],
    instructions="You are a specialized agent that can search the web and extract content from URLs using Tavily. You can help users find information and extract detailed content from web pages.",
    enable_user_memories=True,
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
)

# Create AgentOS with the agent
agent_os = AgentOS(
    name="Tavily Test OS",
    description="AgentOS for testing Tavily search and extract capabilities",
    agents=[tavily_agent],
)
# Get the FastAPI app
app = agent_os.get_app()

if __name__ == "__main__":
    print("✅ AgentOS created successfully!")
    print(f"Agent name: {tavily_agent.name}")
    print(f"Available tools: {[tool.name for tool in tavily_agent.tools]}")
    # Start the server
    agent_os.serve(
        app="testdel:app", 
        host="localhost", 
        port=7780, 
        reload=True
    )

