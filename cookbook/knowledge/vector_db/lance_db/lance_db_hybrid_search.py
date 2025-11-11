from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.vectordb.lancedb import LanceDb, SearchType

knowledge = Knowledge(
    name="My PG Vector Knowledge Base",
    description="This is a knowledge base that uses a PG Vector DB",
    vector_db=LanceDb(
        table_name="vectors",
        uri="tmp/lancedb",
        search_type=SearchType.hybrid,
    ),
)

knowledge.add_content(
    name="Recipes",
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    metadata={"doc_type": "recipe_book"},
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    knowledge=knowledge,
    search_knowledge=True,
    markdown=True,
)
agent.print_response(
    "How do I make chicken and galangal in coconut milk soup", stream=True
)
