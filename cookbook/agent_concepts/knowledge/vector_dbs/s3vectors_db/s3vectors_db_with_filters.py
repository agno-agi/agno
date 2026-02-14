"""Example of using S3Vectors with metadata filtering capabilities."""

from agno.agent import Agent
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.models.openai import OpenAIChat
from agno.vectordb.s3vectors import S3VectorsDb


def main():
    """Run S3Vectors with metadata filtering example."""
    knowledge_base = PDFUrlKnowledgeBase(
        urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
        vector_db=S3VectorsDb(
            bucket_name="recipe-vectors",
            index_name="recipe-index-filtered",
            dimension=1536,
            region_name="us-east-1",
            non_filterable_metadata_keys=["description", "source"],
        ),
    )

    # Load the knowledge base (set recreate=True on first run)
    knowledge_base.load(recreate=False)

    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        knowledge=knowledge_base,
        search_knowledge=True,
        read_chat_history=True,
        show_tool_calls=True,
        markdown=True,
    )

    # Ask about a specific recipe
    agent.print_response(
        "How do I make chicken and galangal in coconut milk soup", stream=True
    )
    
    # Test chat history functionality
    agent.print_response("What was my last question?", stream=True)


if __name__ == "__main__":
    main()
