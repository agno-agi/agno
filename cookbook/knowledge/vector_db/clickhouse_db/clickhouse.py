from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.clickhouse import Clickhouse

vector_db = Clickhouse(
    table_name="recipe_documents",
    host="localhost",
    port=8123,
    username="ai",
    password="ai",
)

knowledge = Knowledge(
    name="My Clickhouse Knowledge Base",
    description="This is a knowledge base that uses a Clickhouse DB",
    vector_db=vector_db,
)

knowledge.add_content(
    name="Recipes",
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    metadata={"doc_type": "recipe_book"},
)

agent = Agent(
    knowledge=knowledge,
    # Enable the agent to search the knowledge base
    search_knowledge=True,
    # Enable the agent to read the chat history
    read_chat_history=True,
)

agent.print_response("How do I make pad thai?", markdown=True)

vector_db.delete_by_name("Recipes")
# or
vector_db.delete_by_metadata({"doc_type": "recipe_book"})
