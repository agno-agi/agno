"""
EaseMyTrip Knowledge Base Loader

This script loads EaseMyTrip's Terms & Conditions from their website
into a vector database for semantic search and retrieval.
"""

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.website_reader import WebsiteReader
from agno.vectordb.lancedb import LanceDb
from agno.knowledge.embedder.openai import OpenAIEmbedder


def create_knowledge_base() -> Knowledge:
    """
    Create and populate the EaseMyTrip knowledge base.

    Returns:
        Knowledge: Populated knowledge base with T&C
    """
    # Create Knowledge Base for EaseMyTrip Terms & Conditions
    easemytrip_kb = Knowledge(
        name="EaseMyTrip Knowledge Base",
        description="Terms & Conditions, Policies, and Customer Support Guidelines from EaseMyTrip",
        vector_db=LanceDb(
            table_name="easemytrip_terms",
            uri="tmp/lancedb",
            embedder=OpenAIEmbedder(
                id="text-embedding-3-small",
                dimensions=1536
            )
        )
    )

    return easemytrip_kb


def load_terms_and_conditions(knowledge_base: Knowledge) -> None:
    """
    Load Terms & Conditions from EaseMyTrip website.

    Args:
        knowledge_base: The knowledge base to load content into
    """
    print("📚 Loading EaseMyTrip Terms & Conditions...")
    print("🌐 Source: https://www.easemytrip.com/terms.html")

    try:
        # Load Terms & Conditions from URL
        knowledge_base.add_contents(
            urls=["https://www.easemytrip.com/terms.html"],
            reader=WebsiteReader(
                max_depth=1,     # Only the terms page, don't crawl
                max_links=1,     # Don't follow other links
                timeout=30       # 30 second timeout
            )
        )

        print("✅ Knowledge Base loaded successfully!")
        print(f"📊 Vector database: tmp/lancedb/easemytrip_terms")

    except Exception as e:
        print(f"❌ Error loading knowledge base: {e}")
        print("⚠️  Make sure you have internet connection and the URL is accessible")
        raise


# Create the knowledge base instance (will be imported by other modules)
easemytrip_kb = create_knowledge_base()


if __name__ == "__main__":
    """
    Run this script to load/reload the knowledge base.

    Usage:
        python knowledge_loader.py
    """
    print("="*60)
    print("EaseMyTrip Knowledge Base Loader")
    print("="*60)
    print()

    # Load the knowledge base
    load_terms_and_conditions(easemytrip_kb)

    print()
    print("="*60)
    print("✅ Setup Complete!")
    print("="*60)
    print()
    print("Next steps:")
    print("1. Test the agent: python test_voice_agent.py")
    print("2. Run web interface: streamlit run streamlit_app.py")
    print("3. Deploy as API: python app.py")
