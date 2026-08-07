"""
Per-User Isolation: Upstash
===========================
Each user gets a private view of one shared knowledge base. Documents
uploaded with a user_id are visible only to that user; documents uploaded
without one are shared with everyone.

Upstash stores the owner in each vector's metadata; shared chunks omit the
field and scoped reads filter user_id = X OR HAS NOT FIELD user_id. The Upstash
wrapper has no async lifecycle methods, so this demo runs the sync path.

- Search as Alice: her chunks plus shared content, never Bob's
- Search as Bob: his chunks plus shared content, never Alice's
- Search with user_id=None: admin view, sees everything

This clears every vector in the configured Upstash index on every run.

Requirements:
- uv pip install upstash-vector
- UPSTASH_VECTOR_REST_URL, UPSTASH_VECTOR_REST_TOKEN (an index with 1536 dimensions)
- OPENAI_API_KEY
"""

import time
from os import getenv
from typing import List

from agno.knowledge.document import Document
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.upstashdb import UpstashVectorDb

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

ALICE_SALARY = "Alice's salary is $180,000. Reviewed annually in March."
BOB_SALARY = "Bob's salary is $215,000. Reviewed annually in June."
HOLIDAYS = "The company is closed on January 1, July 4, and December 25."


def show(label: str, results: List[Document]) -> None:
    """Print one search result set."""
    print(f"{label} -> {len(results)} results")
    for d in results:
        print(f"  - {d.content[:80]}")
    print()


# ---------------------------------------------------------------------------
# Create Knowledge Base
# ---------------------------------------------------------------------------

vector_db = UpstashVectorDb(
    url=getenv("UPSTASH_VECTOR_REST_URL"),
    token=getenv("UPSTASH_VECTOR_REST_TOKEN"),
    embedder=OpenAIEmbedder(),
)

# Start clean. Upstash cannot drop an index over the API, so the vectors are
# deleted instead and the delete is given time to propagate.
vector_db.delete(delete_all=True)
time.sleep(2)

knowledge = Knowledge(
    name="per_user_demo",
    description="Per-user RAG isolation demo (Upstash)",
    vector_db=vector_db,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    def main() -> None:
        # Alice and Bob upload private docs; the last upload has no user_id,
        # which makes it shared / org-wide content.
        knowledge.insert(
            name="alice_salary",
            text_content=ALICE_SALARY,
            user_id="alice",
        )
        knowledge.insert(
            name="bob_salary",
            text_content=BOB_SALARY,
            user_id="bob",
        )
        knowledge.insert(
            name="company_holidays",
            text_content=HOLIDAYS,
        )

        # Upstash upserts are eventually consistent; let them settle.
        time.sleep(5)

        print("\n" + "=" * 60)
        print("SCOPED SEARCH: three callers, one corpus")
        print("=" * 60 + "\n")

        alice_view = knowledge.search(query="salary", user_id="alice")
        show("Alice (user_id='alice')", alice_view)
        alice_text = " ".join(d.content for d in alice_view)
        assert "180,000" in alice_text, "Alice cannot retrieve her own document"
        assert "January 1" in alice_text, (
            "Shared content is unreachable from Alice's scoped view"
        )
        assert "215,000" not in alice_text, (
            "Isolation broken: Alice's scoped view leaked Bob's salary"
        )

        bob_view = knowledge.search(query="salary", user_id="bob")
        show("Bob (user_id='bob')", bob_view)
        bob_text = " ".join(d.content for d in bob_view)
        assert "215,000" in bob_text, "Bob cannot retrieve his own document"
        assert "January 1" in bob_text, (
            "Shared content is unreachable from Bob's scoped view"
        )
        assert "180,000" not in bob_text, (
            "Isolation broken: Bob's scoped view leaked Alice's salary"
        )

        admin_view = knowledge.search(query="salary", user_id=None)
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

    main()
