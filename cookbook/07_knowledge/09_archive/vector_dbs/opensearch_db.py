from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.opensearch import OpenSearch

knowledge = Knowledge(
    name="OpenSearch Recipe Knowledge Base",
    description="This is a knowledge base that uses OpenSearch",
    vector_db=OpenSearch(
        index_name="recipe",
    ),
)

knowledge.add_content(
    name="Thai Recipes",
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    metadata={"doc_type": "recipe_book"},
)

agent = Agent(
    knowledge=knowledge,
    # Enable the agent to search the knowledge base
    search_knowledge=True,
    # A db is required for the agent to read its own chat history
    db=SqliteDb(db_file="tmp/opensearch.db"),
    # Enable the agent to read the chat history
    read_chat_history=True,
)
agent.print_response("How to make Thai curry?")
