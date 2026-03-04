from typing import Optional

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.team.team import Team
from agno.vectordb.qdrant import Qdrant
from qdrant_client import QdrantClient

# ---------------------------------------------------------
# This section loads the knowledge base. Skip if your knowledge base was populated elsewhere.
# Define the embedder
embedder = OpenAIEmbedder(id="text-embedding-3-small")
# Initialize vector database connection
vector_db = Qdrant(
    collection="thai-recipes", url="http://localhost:6333", embedder=embedder
)
# Load the knowledge base
knowledge = Knowledge(
    vector_db=vector_db,
)

knowledge.insert(
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
)

# ---------------------------------------------------------


# Define the custom knowledge retriever
def knowledge_retriever(
    query: str, team: Optional[Team] = None, num_documents: int = 5, **kwargs
) -> Optional[list[dict]]:
    """
    Custom knowledge retriever function for a Team.

    Args:
        query (str): The search query string
        team (Team): The team instance making the query
        num_documents (int): Number of documents to retrieve (default: 5)
        **kwargs: Additional keyword arguments

    Returns:
        Optional[list[dict]]: List of retrieved documents or None if search fails
    """
    try:
        qdrant_client = QdrantClient(url="http://localhost:6333")
        query_embedding = embedder.get_embedding(query)
        results = qdrant_client.query_points(
            collection_name="thai-recipes",
            query=query_embedding,
            limit=num_documents,
        )
        results_dict = results.model_dump()
        if "points" in results_dict:
            return results_dict["points"]
        else:
            return None
    except Exception as e:
        print(f"Error during vector database search: {str(e)}")
        return None


def main():
    """Main function to demonstrate team usage with a custom knowledge retriever."""
    # Create a member agent that summarizes recipes
    summary_agent = Agent(
        name="Summary Agent",
        role="Summarize and format recipe information into clear, readable responses",
    )

    # Initialize team with custom knowledge retriever
    # The team searches the knowledge base directly using the custom retriever,
    # then delegates formatting tasks to the summary agent.
    team = Team(
        name="Recipe Team",
        members=[summary_agent],
        knowledge=knowledge,
        knowledge_retriever=knowledge_retriever,
        search_knowledge=True,
        instructions=[
            "Always use the search_knowledge_base tool to find recipe information before delegating to members.",
            "Delegate to the Summary Agent only for formatting the results.",
        ],
    )

    # Example query
    query = "List down the ingredients to make Massaman Gai"
    team.print_response(query, markdown=True)


if __name__ == "__main__":
    main()
