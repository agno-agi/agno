import typer
from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.search import SearchType
from agno.vectordb.weaviate import Distance, VectorIndex, Weaviate
from rich.prompt import Prompt

vector_db = Weaviate(
    collection="recipes",
    search_type=SearchType.hybrid,
    vector_index=VectorIndex.HNSW,
    distance=Distance.COSINE,
    local=False,  # Set to True if using Weaviate Cloud and False if using local instance
    # Adjust alpha for hybrid search (0.0-1.0, default is 0.5), where 0 is pure keyword search, 1 is pure vector search
    hybrid_search_alpha=0.6,
)

knowledge_base = Knowledge(
    name="Weaviate Hybrid Search",
    description="A knowledge base for Weaviate hybrid search",
    vector_db=vector_db,
)

knowledge_base.add_content(
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
)


def weaviate_agent(user: str = "user"):
    agent = Agent(
        user_id=user,
        knowledge=knowledge_base,
        search_knowledge=True,
    )

    while True:
        message = Prompt.ask(f"[bold] :sunglasses: {user} [/bold]")
        if message in ("exit", "bye"):
            break
        agent.print_response(message)


if __name__ == "__main__":
    typer.run(weaviate_agent)
