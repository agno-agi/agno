"""
Per-User Knowledge Isolation with Upstash
=========================================
Each user gets a private view of one shared knowledge base. Documents
uploaded with a user_id are visible only to that user; documents uploaded
without one are shared with everyone.

Upstash stores the owner in each vector's metadata; shared chunks omit the
field and scoped reads filter user_id = X OR HAS NOT FIELD user_id. The
Upstash wrapper has no async lifecycle methods, so this demo runs the
sync insert / search path.

- Search as Alice: her chunks plus shared content, never Bob's
- Search as Bob: his chunks plus shared content, never Alice's
- Search with user_id=None: admin view, sees everything

Requirements: UPSTASH_VECTOR_REST_URL, UPSTASH_VECTOR_REST_TOKEN (index
with 1536 dimensions) and OPENAI_API_KEY
Run: python cookbook/07_knowledge/04_advanced/07_per_user_isolation/upstash_db.py
"""

import time
from os import getenv
from pathlib import Path

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.upstashdb import UpstashVectorDb


def _write_temp_doc(name: str, body: str) -> str:
    """Write a tiny text file we can ingest. Returns the absolute path."""
    p = Path(f"/tmp/{name}")
    p.write_text(body)
    return str(p)


def main() -> None:
    vector_db = UpstashVectorDb(
        url=getenv("UPSTASH_VECTOR_REST_URL"),
        token=getenv("UPSTASH_VECTOR_REST_TOKEN"),
        embedder=OpenAIEmbedder(),
    )

    # Upstash can't DROP an index via the API, so start clean by deleting
    # all vectors and letting the delete propagate (eventually consistent).
    try:
        vector_db.delete(delete_all=True)
    except Exception:
        pass
    time.sleep(2)

    knowledge = Knowledge(
        name="per_user_demo",
        description="Per-user RAG isolation demo (Upstash)",
        vector_db=vector_db,
    )

    # Alice and Bob upload private docs; the last upload has no user_id,
    # which makes it shared / org-wide content.
    knowledge.insert(
        path=_write_temp_doc(
            "alice_salary.txt",
            "Alice's salary is $180,000. Reviewed annually in March.",
        ),
        name="alice_salary",
        user_id="alice",
    )

    knowledge.insert(
        path=_write_temp_doc(
            "bob_salary.txt",
            "Bob's salary is $215,000. Reviewed annually in June.",
        ),
        name="bob_salary",
        user_id="bob",
    )

    knowledge.insert(
        path=_write_temp_doc(
            "company_holidays.txt",
            "The company is closed on January 1, July 4, and December 25.",
        ),
        name="company_holidays",
    )

    # Give the upserts a moment to become queryable.
    time.sleep(2)

    print("\n=== Direct search tests ===\n")

    alice_salary = knowledge.search(query="What is Alice's salary?", user_id="alice")
    print(f"Alice asks about Alice's salary -> {len(alice_salary)} results")
    for d in alice_salary:
        print(f"  - {d.content[:80]}  (owner={d.meta_data.get('user_id')!r})")
    assert alice_salary, "expected Alice's own results, got none"

    alice_about_bob = knowledge.search(query="What is Bob's salary?", user_id="alice")
    print(f"\nAlice asks about Bob's salary -> {len(alice_about_bob)} results")
    for d in alice_about_bob:
        print(f"  - {d.content[:80]}  (owner={d.meta_data.get('user_id')!r})")
    bob_chunks = [d for d in alice_about_bob if d.meta_data.get("user_id") == "bob"]
    assert not bob_chunks, "Isolation broken: Alice's retrieval surfaced Bob's chunks"
    print("  isolation holds: Bob's chunks are NOT visible to Alice")

    bob_holidays = knowledge.search(query="When is the company closed?", user_id="bob")
    print(f"\nBob asks about holidays -> {len(bob_holidays)} results")
    for d in bob_holidays:
        print(f"  - {d.content[:80]}  (owner={d.meta_data.get('user_id')!r})")

    admin_view = knowledge.search(query="salary", user_id=None)
    print(f"\nAdmin asks about salary (user_id=None) -> {len(admin_view)} results")
    for d in admin_view:
        print(f"  - {d.content[:80]}  (owner={d.meta_data.get('user_id')!r})")

    print("\n=== Agent-mediated test ===\n")

    # The agent's user_id flows into run_context and scopes its retrieval.
    alice_agent = Agent(
        name="Alice's Assistant",
        model=OpenAIResponses(id="gpt-5.5"),
        knowledge=knowledge,
        user_id="alice",
        instructions=[
            "Answer questions using ONLY the knowledge you can retrieve.",
            "If you don't know, say so - do not invent salary figures.",
        ],
        markdown=True,
    )

    response = alice_agent.run("What is Bob's salary?")
    print("Alice's agent on 'What is Bob's salary?':")
    print(response.content)

    print("\nDone.")


if __name__ == "__main__":
    main()
