"""
Per-User Isolation: Chroma
==========================
Each user gets a private view of one shared knowledge base. Documents
uploaded with a user_id are visible only to that user; documents uploaded
without one are shared with everyone.

Chroma gives each user their own collection ({base}__{user_id}); the base
collection is the shared bucket. Scoped searches query the caller's collection
plus the base one and merge by distance.

- Search as Alice: her chunks plus shared content, never Bob's
- Search as Bob: his chunks plus shared content, never Alice's
- Search with user_id=None: admin view, sees everything

Requirements:
- uv pip install chromadb (embedded, no server)
- OPENAI_API_KEY
"""

import asyncio
from typing import List

from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.chroma import ChromaDb

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

ALICE_SALARY = "Alice's salary is $180,000. Reviewed annually in March."
BOB_SALARY = "Bob's salary is $215,000. Reviewed annually in June."
HOLIDAYS = "The company is closed on January 1, July 4, and December 25."

DB_PATH = "tmp/per_user_isolation_chromadb"
COLLECTION_NAME = "per_user_isolation_demo"


def show(label: str, results: List[Document]) -> None:
    """Print one search result set."""
    print(f"{label} -> {len(results)} results")
    for d in results:
        print(f"  - {d.content[:80]}")
    print()


# ---------------------------------------------------------------------------
# Create Knowledge Base
# ---------------------------------------------------------------------------

vector_db = ChromaDb(collection=COLLECTION_NAME, path=DB_PATH)

# Start clean: collections left by an earlier run still carry their owner and
# would show up as extra results below. drop() also removes the per-user
# collections that share this base name.
if vector_db.exists():
    vector_db.drop()
vector_db.create()

knowledge = Knowledge(
    name="per_user_demo",
    description="Per-user RAG isolation demo (ChromaDB)",
    vector_db=vector_db,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def main() -> None:
        # Alice and Bob upload private docs; the last upload has no user_id,
        # which makes it shared / org-wide content.
        await knowledge.ainsert(
            name="alice_salary",
            text_content=ALICE_SALARY,
            user_id="alice",
        )
        await knowledge.ainsert(
            name="bob_salary",
            text_content=BOB_SALARY,
            user_id="bob",
        )
        await knowledge.ainsert(
            name="company_holidays",
            text_content=HOLIDAYS,
        )

        print("\n" + "=" * 60)
        print("SCOPED SEARCH: three callers, one corpus")
        print("=" * 60 + "\n")

        alice_view = await knowledge.asearch(query="salary", user_id="alice")
        show("Alice (user_id='alice')", alice_view)
        alice_text = " ".join(d.content for d in alice_view)
        assert "180,000" in alice_text, "Alice cannot retrieve her own document"
        assert "January 1" in alice_text, (
            "Shared content is unreachable from Alice's scoped view"
        )
        assert "215,000" not in alice_text, (
            "Isolation broken: Alice's scoped view leaked Bob's salary"
        )

        bob_view = await knowledge.asearch(query="salary", user_id="bob")
        show("Bob (user_id='bob')", bob_view)
        bob_text = " ".join(d.content for d in bob_view)
        assert "215,000" in bob_text, "Bob cannot retrieve his own document"
        assert "January 1" in bob_text, (
            "Shared content is unreachable from Bob's scoped view"
        )
        assert "180,000" not in bob_text, (
            "Isolation broken: Bob's scoped view leaked Alice's salary"
        )

        admin_view = await knowledge.asearch(query="salary", user_id=None)
        show("Admin (user_id=None)", admin_view)
        admin_text = " ".join(d.content for d in admin_view)
        for expected in ("180,000", "215,000", "January 1"):
            assert expected in admin_text, (
                f"Admin view is missing {expected}, it has to see every owner"
            )
        assert all(d.content in admin_text for d in alice_view), (
            "Admin view has to be a superset of a scoped user's view"
        )
        print("Alice and Bob each see their own chunk plus the shared one.")
        print("Admin sees the whole corpus.")

        print("\nDone.")

    asyncio.run(main())
