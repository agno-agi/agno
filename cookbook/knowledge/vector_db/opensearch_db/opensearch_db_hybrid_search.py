from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.vectordb.opensearch import OpensearchDb
from agno.vectordb.search import SearchType

knowledge = Knowledge(
    name="OpenSearch Hybrid Search Recipe Knowledge Base",
    description="This is a knowledge base that uses OpenSearch with hybrid search",
    vector_db=OpensearchDb(
        index_name="recipe_hybrid",
        dimension=1536,
        search_type=SearchType.hybrid,
        hosts=[
            {
                "host": "localhost",
                "port": 9200,
            }
        ],
        # Uncomment the following line to use basic authentication
        # http_auth=("username", "password"),
    )
)

knowledge.add_content(
    name="Thai Recipes",
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    metadata={"doc_type": "recipe_book"},
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    knowledge=knowledge,
    search_knowledge=True,
    read_chat_history=True,
    markdown=True,
)
agent.print_response(
    "How do I make chicken and galangal in coconut milk soup", stream=True
)
agent.print_response("What was my last question?", stream=True)
