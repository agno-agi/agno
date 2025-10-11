import asyncio

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.opensearch import OpensearchDb

vector_db = OpensearchDb(
    index_name="recipe_async",
    dimension=1536,
    hosts=[
        {
            "host": "localhost",
            "port": 9200,
        }
    ],
    # Uncomment the following line to use basic authentication
    # http_auth=("username", "password"),

)

knowledge_base = Knowledge(
    vector_db=vector_db,
)

agent = Agent(knowledge=knowledge_base)

if __name__ == "__main__":
    # Comment out after first run
    asyncio.run(
        knowledge_base.add_content_async(
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
        )
    )

    # Create and use the agent
    asyncio.run(
        agent.aprint_response("How to make Tom Kha Gai", markdown=True)
    )
