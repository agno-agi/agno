"""This cookbook shows how to load a directory of files with authentication credentials.

When loading directories, authentication and metadata propagate to all files:
- auth: Password for encrypted PDFs, API keys for remote sources
- topics: Categories applied to all content
- metadata: Custom fields inherited by all files

Run: `python cookbook/08_knowledge/basic_operations/sync/16_directory_with_credentials.py`
"""

from agno.agent import Agent
from agno.knowledge.content import Content, ContentAuth
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge = Knowledge(
    vector_db=PgVector(table_name="directory_credentials_example", db_url=db_url),
)

# Load directory with auth and topics - these propagate to all files
print("Loading directory with credentials and metadata...")
knowledge.insert(
    sources=[
        Content(
            name="Engineering Documentation",
            path="cookbook/08_knowledge/testing_resources/",
            description="Technical documentation",
            # Auth propagates to all files in subdirectories
            auth=ContentAuth(password="optional_pdf_password"),
            # Topics are inherited by all child content
            topics=["engineering", "documentation"],
            # Metadata is preserved throughout the directory tree
            metadata={"department": "engineering"},
        )
    ]
)
print("  Directory loaded successfully")

# Create agent and query
agent = Agent(
    knowledge=knowledge,
    search_knowledge=True,
)

print("\nQuerying the knowledge base...")
agent.print_response(
    "What skills and experience are mentioned in the documentation?",
    markdown=True,
)
