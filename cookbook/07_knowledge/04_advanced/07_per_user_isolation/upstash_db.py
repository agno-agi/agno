"""
Per-User Knowledge Isolation with Upstash
=========================================
Give each user a private view of one shared knowledge base. Documents a user
uploads are visible only to them; documents uploaded with no user are shared
with everyone, and an admin (no user id) sees all of it.

Upstash does this by storing the owner in each vector's metadata and filtering
on it, treating vectors with no owner field as shared.
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
    # ------------------------------------------------------------------
    # Set up a Knowledge instance backed by Upstash Vector.
    # ------------------------------------------------------------------
    vector_db = UpstashVectorDb(
        url=getenv("UPSTASH_VECTOR_REST_URL"),
        token=getenv("UPSTASH_VECTOR_REST_TOKEN"),
        embedder=OpenAIEmbedder(),
    )
    # Start clean. Upstash can't DROP an index via the API (only the Console),
    # so delete all vectors instead — drop() is a no-op here.
    try:
        vector_db.delete(delete_all=True)
    except Exception:
        pass
    # Let the delete propagate before re-inserting (Upstash is eventually consistent).
    time.sleep(2)

    knowledge = Knowledge(
        name="per_user_demo",
        description="Per-user RAG isolation demo (Upstash)",
        vector_db=vector_db,
    )

    # ------------------------------------------------------------------
    # Three uploads: Alice (private), Bob (private), Admin (shared).
    # The ``user_id`` kwarg on ``insert`` flows through to every chunk
    # written to Upstash — it is stamped onto ``meta_data["user_id"]``
    # that the search filter scopes on.
    # ------------------------------------------------------------------
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
        # No ``user_id`` — this is org-wide / admin-uploaded shared content.
        # In Upstash the metadata omits the ``user_id`` field; scoped
        # searches match it via ``OR HAS NOT FIELD user_id``.
    )

    # Upstash is eventually consistent; give the upserts a moment to be queryable.
    time.sleep(2)

    # ------------------------------------------------------------------
    # Demonstrate the isolation contract DIRECTLY against Knowledge.
    # ------------------------------------------------------------------
    print("\n=== Direct search tests ===\n")

    # 1. Alice asks about her own salary — she should find HER chunk.
    alice_salary = knowledge.search(query="What is Alice's salary?", user_id="alice")
    print(f"Alice asks about Alice's salary -> {len(alice_salary)} results")
    for d in alice_salary:
        print(f"  - {d.content[:80]}  (owner={d.meta_data.get('user_id')!r})")

    # 2. Alice asks about Bob — she should NOT see Bob's chunk. Best she can
    #    do is the shared holidays doc, which is unrelated.
    alice_about_bob = knowledge.search(query="What is Bob's salary?", user_id="alice")
    print(f"\nAlice asks about Bob's salary -> {len(alice_about_bob)} results")
    for d in alice_about_bob:
        print(f"  - {d.content[:80]}  (owner={d.meta_data.get('user_id')!r})")
    bob_chunks_in_alices_results = [
        d for d in alice_about_bob if d.meta_data.get("user_id") == "bob"
    ]
    assert not bob_chunks_in_alices_results, (
        "Isolation broken: Alice's retrieval surfaced Bob's chunks"
    )
    print("  isolation holds: Bob's chunks are NOT visible to Alice")

    # 3. Bob asks about company holidays — he should see the SHARED chunk.
    bob_holidays = knowledge.search(query="When is the company closed?", user_id="bob")
    print(f"\nBob asks about holidays -> {len(bob_holidays)} results")
    for d in bob_holidays:
        print(f"  - {d.content[:80]}  (owner={d.meta_data.get('user_id')!r})")

    # 4. Admin / no scope passed — sees everything.
    admin_view = knowledge.search(query="salary", user_id=None)
    print(f"\nAdmin asks about salary (user_id=None) -> {len(admin_view)} results")
    for d in admin_view:
        print(f"  - {d.content[:80]}  (owner={d.meta_data.get('user_id')!r})")

    # ------------------------------------------------------------------
    # End-to-end: an Agent doing RAG-as-Alice never sees Bob's chunks.
    # The ``user_id`` is threaded through Knowledge.search from whatever
    # caller (an OS router, a custom tool, your own code) decides the
    # right owner is. For this demo we pass it explicitly.
    # ------------------------------------------------------------------
    print("\n=== Agent-mediated test ===\n")
    alice_agent = Agent(
        name="Alice's Assistant",
        model=OpenAIResponses(id="gpt-5.4"),
        knowledge=knowledge,
        # Pin the agent to Alice's identity for retrieval. In a real
        # deployment this comes from JWT.sub / get_scoped_user_id(request).
        user_id="alice",
        instructions=[
            "Answer questions using ONLY the knowledge you can retrieve.",
            "If you don't know, say so — do not invent salary figures.",
        ],
        markdown=True,
    )
    response = alice_agent.run("What is Bob's salary?")
    print("Alice's agent on 'What is Bob's salary?':")
    print(response.content)
    print("\nDone.")


if __name__ == "__main__":
    main()
