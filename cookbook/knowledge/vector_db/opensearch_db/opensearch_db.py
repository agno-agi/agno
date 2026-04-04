from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.opensearch import OpensearchDb

knowledge = Knowledge(
    name="OpenSearch Recipe Knowledge Base",
    description="This is a knowledge base that uses OpenSearch",
    vector_db=OpensearchDb(
        index_name="recipe",
        dimension=1536,
        hosts=[
            {
                "host": "localhost",
                "port": 9200,
            }
        ],
        # Uncomment the following line to use basic authentication
        # http_auth=("username", "password"),
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
    # Enable the agent to read the chat history
    read_chat_history=True,
)
agent.print_response("How to make Thai curry?")
