from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.opensearch import OpenSearch
from agno.vectordb.search import SearchType

knowledge = Knowledge(
    name="OpenSearch Hybrid Search Recipe Knowledge Base",
    description="This is a knowledge base that uses OpenSearch with hybrid search",
    vector_db=OpenSearch(
        index_name="recipe_hybrid",
        search_type=SearchType.hybrid,
    ),
)

knowledge.add_content(
    name="Thai Recipes",
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    metadata={"doc_type": "recipe_book"},
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    knowledge=knowledge,
    search_knowledge=True,
    # A db is required for the agent to read its own chat history
    db=SqliteDb(db_file="tmp/opensearch_hybrid.db"),
    read_chat_history=True,
    markdown=True,
)
agent.print_response(
    "How do I make chicken and galangal in coconut milk soup", stream=True
)
agent.print_response("What was my last question?", stream=True)
