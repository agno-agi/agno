"""
Prefix Search: Help Center with search-as-you-type
===================================================
Real-world use case: A help center where users search for articles
while typing, getting instant results for partial words.

Example: User types "auth" and immediately sees articles about
"authentication", "authorization", "authenticator app", etc.

Without prefix_match: User must type complete words to get matches.
With prefix_match=True: Partial words match, enabling typeahead search.
"""

from agno.knowledge.document import Document
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.vectordb.pgvector import PgVector
from agno.vectordb.search import SearchType

# ---------------------------------------------------------------------------
# Setup: Help Center knowledge base with prefix matching
# ---------------------------------------------------------------------------

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Help center with prefix search enabled for typeahead
help_center = PgVector(
    table_name="help_center_articles",
    db_url=db_url,
    search_type=SearchType.hybrid,
    prefix_match=True,  # enables search-as-you-type
    embedder=OpenAIEmbedder(id="text-embedding-3-small"),
)

# Same database without prefix matching (for comparison)
help_center_standard = PgVector(
    table_name="help_center_articles",
    db_url=db_url,
    search_type=SearchType.hybrid,
    prefix_match=False,  # default - exact word match only
    embedder=OpenAIEmbedder(id="text-embedding-3-small"),
)

# ---------------------------------------------------------------------------
# Sample help articles
# ---------------------------------------------------------------------------

help_articles = [
    Document(
        name="auth-setup",
        content="Setting up authentication: Configure two-factor authentication (2FA) "
        "using an authenticator app like Google Authenticator or Authy.",
    ),
    Document(
        name="auth-troubleshoot",
        content="Authentication troubleshooting: Common issues with login, "
        "password reset, and authentication token expiration.",
    ),
    Document(
        name="authorization",
        content="Authorization and permissions: How to configure role-based access "
        "control (RBAC) and manage user authorization levels.",
    ),
    Document(
        name="api-keys",
        content="API key management: Generate, rotate, and revoke API keys "
        "for programmatic access to your account.",
    ),
    Document(
        name="billing",
        content="Billing and payments: Update payment methods, view invoices, "
        "and manage your subscription plan.",
    ),
]

# ---------------------------------------------------------------------------
# Demo: Simulate user typing "auth" in search box
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Setup
    help_center.create()
    help_center.upsert(documents=help_articles, content_hash="v1")

    print("=" * 60)
    print("Help Center Search Demo")
    print("=" * 60)

    # Simulate user typing progressively
    search_queries = ["au", "auth", "authent"]

    for query in search_queries:
        print(f"\nUser types: '{query}'")
        print("-" * 40)

        # Without prefix matching
        print("Standard search (prefix_match=False):")
        results = help_center_standard.search(query, limit=2)
        for doc in results:
            score = doc.meta_data.get("similarity_score", 0)
            print(f"  [{score:.2f}] {doc.name}: {doc.content[:40]}...")

        # With prefix matching
        print("\nTypeahead search (prefix_match=True):")
        results = help_center.search(query, limit=2)
        for doc in results:
            score = doc.meta_data.get("similarity_score", 0)
            print(f"  [{score:.2f}] {doc.name}: {doc.content[:40]}...")

    print("\n" + "=" * 60)
    print("prefix_match=True finds 'authentication' when user types 'auth'")
    print("=" * 60)
