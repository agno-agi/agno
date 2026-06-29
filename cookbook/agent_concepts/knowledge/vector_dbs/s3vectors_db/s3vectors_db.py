"""Example of using S3Vectors with synchronous operations for knowledge base queries."""

from agno.agent import Agent
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.vectordb.s3vectors import S3VectorsDb


def main():
    """Run S3Vectors knowledge base example."""
    vector_db = S3VectorsDb(
        bucket_name="recipe-vectors",
        index_name="recipe-index",
        dimension=1536,
        region_name="us-east-1",
    )

    knowledge_base = PDFUrlKnowledgeBase(
        urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
        vector_db=vector_db,
    )

    # Load the knowledge base (set recreate=True on first run)
    knowledge_base.load(recreate=False)

    agent = Agent(knowledge=knowledge_base, show_tool_calls=True)
    agent.print_response("How to make Thai curry?", markdown=True)


if __name__ == "__main__":
    main()
