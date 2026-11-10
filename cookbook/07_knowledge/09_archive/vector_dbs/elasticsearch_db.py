from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.elasticsearch import Elasticsearch

knowledge = Knowledge(
    name="Elasticsearch Recipe Knowledge Base",
    description="This is a knowledge base that uses Elasticsearch",
    vector_db=Elasticsearch(
        index_name="recipe",
    ),
)

knowledge.insert(
    name="Thai Recipes",
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    metadata={"doc_type": "recipe_book"},
)

agent = Agent(
    knowledge=knowledge,
    # Enable the agent to search the knowledge base
    search_knowledge=True,
    # A db is required for the agent to read its own chat history
    db=SqliteDb(db_file="tmp/elasticsearch.db"),
    # Enable the agent to read the chat history
    read_chat_history=True,
)
agent.print_response("How to make Thai curry?")
