"""
Load Knowledge Documents
========================

Script to load support documentation into the knowledge base.
Run this before using the customer support agent.

Usage:
    # Start PostgreSQL first
    ./cookbook/scripts/run_pgvector.sh

    # Load knowledge documents
    .venvs/demo/bin/python cookbook/01_showcase/01_agents/customer_support/scripts/load_knowledge.py
"""

from pathlib import Path

from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector, SearchType

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge"

knowledge = Knowledge(
    name="Support Knowledge Base",
    vector_db=PgVector(
        table_name="support_knowledge",
        db_url=DB_URL,
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    max_results=10,
)

# IT support best practices from the web
IT_SUPPORT_URLS = [
    # Troubleshooting methodology
    "https://www.comptia.org/en-us/blog/use-a-troubleshooting-methodology-for-more-efficient-it-support/",
    "https://sre.google/sre-book/effective-troubleshooting/",
    "https://www.techtarget.com/whatis/definition/troubleshooting",
    # Customer de-escalation techniques
    "https://helpware.com/blog/how-to-deescalate-angry-customer-best-techniques",
    "https://www.indeed.com/career-advice/career-development/de-escalation-techniques-customer-service",
    "https://mailchimp.com/resources/de-escalation-techniques/",
    # First contact resolution / ticket management
    "https://timetoreply.com/blog/how-to-improve-first-contact-resolution/",
    "https://www.helpdesk.com/blog/first-contact-resolution/",
    "https://www.freshworks.com/helpdesk/metrics/",
    # Technical communication skills
    "https://www.visiontrainingsystems.com/blogs/soft-skills-that-make-you-stand-out-as-a-help-desk-technician/",
    "https://cto.academy/communicating-with-non-technical-customers/",
]


# ============================================================================
# Load Documents
# ============================================================================
def load_knowledge_base():
    """Load all documents into the knowledge base."""
    print("Loading customer support knowledge base...")
    print(f"Knowledge directory: {KNOWLEDGE_DIR}")
    print()

    # Load local markdown files
    md_files = list(KNOWLEDGE_DIR.glob("*.md"))
    if md_files:
        print(f"Found {len(md_files)} local documents:")
        for f in md_files:
            print(f"  - {f.name}")
        print()
        print("Loading local documents...")
        knowledge.insert(path=str(KNOWLEDGE_DIR))
        print("  Loaded local documents")

    # Load IT support best practices from URLs
    print()
    print("Loading IT support best practices from web...")
    for url in IT_SUPPORT_URLS:
        print(f"  - {url}")
        knowledge.insert(url=url)
    print("  Loaded web documents")

    print()
    print("Knowledge base loaded successfully.")
    print()
    print("You can now run the examples:")
    print(
        "  .venvs/demo/bin/python cookbook/01_showcase/01_agents/customer_support/basic/simple_query.py"
    )


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    load_knowledge_base()
