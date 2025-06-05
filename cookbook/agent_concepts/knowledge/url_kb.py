"""Agent with Knowledge - An agent that can search a knowledge base

Install dependencies: `pip install openai lancedb tantivy agno`
"""

from pathlib import Path
from textwrap import dedent

from agno.agent import Agent
from agno.knowledge.url import UrlKnowledge
from agno.models.openai import OpenAIChat
from agno.vectordb.lancedb import LanceDb, SearchType

# Setup paths
cwd = Path(__file__).parent
tmp_dir = cwd.joinpath("tmp")
tmp_dir.mkdir(parents=True, exist_ok=True)

# Initialize knowledge base
agent_knowledge = UrlKnowledge(
    urls=["https://docs.agno.com/introduction"],
    vector_db=LanceDb(
        uri=str(tmp_dir.joinpath("lancedb")),
        table_name="agno_assist_knowledge",
        search_type=SearchType.hybrid,
    ),
)

agent_with_knowledge = Agent(
    name="Agent with Knowledge",
    model=OpenAIChat(id="gpt-4o"),
    knowledge=agent_knowledge,
    show_tool_calls=True,
    markdown=True,
)

if __name__ == "__main__":
    # Comment out after first run
    agent_knowledge.load()

    agent_with_knowledge.print_response(
        "Tell me about teams with context to agno", stream=True
    )
