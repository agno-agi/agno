from textwrap import dedent

from agno.agent import Agent
from agno.embedder.openai import OpenAIEmbedder
from agno.knowledge.url import UrlKnowledge
from agno.models.openai import OpenAIChat
from agno.vectordb.lancedb import LanceDb, SearchType

agent_knowledge = UrlKnowledge(
    urls=["https://docs.agno.com/llms-full.txt"],
    vector_db=LanceDb(
        uri="tmp/lancedb",
        table_name="agno_docs",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    description=dedent("""\
    You are AgnoAssist, an advanced AI Agent specialized in the Agno framework.
    Your goal is to help developers effectively use Agno by providing explanations and working code examples"""),
    instructions=dedent("""\
    1. Analyze the request
    2. Search your knowledge base for relevant information
    3. Present the information to the user\
    """),
    knowledge=agent_knowledge,
    add_datetime_to_instructions=True,
    show_tool_calls=True,
    markdown=True,
)

if __name__ == "__main__":
    load_knowledge = False
    if load_knowledge:
        agent_knowledge.load()

    agent.print_response(
        "What is Agno and how do I implement Agentic RAG?", stream=True
    )
