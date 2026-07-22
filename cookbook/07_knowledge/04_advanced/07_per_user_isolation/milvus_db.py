"""Per-user knowledge isolation with Milvus.

Same isolation contract as the pgvector / Qdrant / LanceDB cookbooks in
this directory, against a different backend. The
``Knowledge.asearch(user_id=...)`` API is identical — only the underlying
primitive changes:

  * Milvus stores the owner in a nullable ``user_id`` scalar field. Owned
    chunks carry the uploader's id; shared chunks leave it null.

  * Scoped reads compile to a boolean expression pushed into the search:
    ``user_id == "alice" or user_id is null`` — the caller's bucket OR the
    shared bucket. Passing ``user_id=None`` adds no predicate (admin view,
    sees everything).

Three uploads, four scoped queries:

  1. Alice and Bob each upload private content.
  2. An admin uploads org-wide content (``user_id`` left ``None``).
  3. Alice asks about Alice — sees her chunk plus shared content.
  4. Alice asks about Bob — Bob's private chunk is filtered out.
  5. Bob asks about holidays — sees the shared bucket.
  6. Admin (``user_id=None``) sees everything.

Milvus Lite caveat: with a local-file ``uri`` Milvus runs embedded (no
server), which is perfect for a demo. But Milvus Lite does NOT return
dynamic scalar fields for ``output_fields=["*"]`` (the primitive the
backend uses on read), so retrieved ``Document.content`` / ``meta_data``
come back empty here. The rows and the isolation filter are stored and
applied correctly, so we verify the contract by result COUNT: a scoped
search returns strictly fewer rows than the admin view, with exactly the
other user's private chunk removed. On a full Milvus server the same code
also returns populated content.

Prerequisites:

  * ``pip install pymilvus[milvus-lite]`` — embedded, no server.
  * ``OPENAI_API_KEY`` set in your environment (or swap the model below).

Run:

    python cookbook/07_knowledge/04_advanced/07_per_user_isolation/milvus_db.py
"""

import asyncio
from pathlib import Path

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.milvus import Milvus


def _write_temp_doc(name: str, body: str) -> str:
    """Write a tiny text file we can ingest. Returns the absolute path."""
    p = Path(f"/tmp/{name}")
    p.write_text(body)
    return str(p)


async def main() -> None:
    # ------------------------------------------------------------------
    # A local-file ``uri`` means Milvus Lite (embedded, no server). For a
    # real deployment, point ``uri`` at a Milvus server, e.g.
    # "http://localhost:19530".
    #
    # We create the collection with the SYNC client: Milvus Lite does not
    # implement the async index-creation path, so ``async_create()`` is
    # unavailable here. The rest of the demo (ainsert / asearch) is async.
    # ------------------------------------------------------------------
    vector_db = Milvus(
        collection="per_user_isolation_demo",
        uri="/tmp/milvus_per_user_isolation.db",
    )
    vector_db.drop()
    vector_db.create()

    knowledge = Knowledge(
        name="per_user_demo",
        description="Per-user RAG isolation demo (Milvus)",
        vector_db=vector_db,
    )

    # ------------------------------------------------------------------
    # Three uploads: Alice (private), Bob (private), Admin (shared).
    # The ``user_id`` kwarg on ``ainsert`` flows through to the Milvus
    # backend, which stamps it onto the ``user_id`` field. The API call is
    # identical to pgvector / Qdrant / LanceDB.
    # ------------------------------------------------------------------
    await knowledge.ainsert(
        path=_write_temp_doc(
            "alice_salary.txt",
            "Alice's salary is $180,000. Reviewed annually in March.",
        ),
        name="alice_salary",
        user_id="alice",
    )

    await knowledge.ainsert(
        path=_write_temp_doc(
            "bob_salary.txt",
            "Bob's salary is $215,000. Reviewed annually in June.",
        ),
        name="bob_salary",
        user_id="bob",
    )

    await knowledge.ainsert(
        path=_write_temp_doc(
            "company_holidays.txt",
            "The company is closed on January 1, July 4, and December 25.",
        ),
        name="company_holidays",
        # No ``user_id`` — this is org-wide / admin-uploaded shared content.
        # Milvus leaves the ``user_id`` field null; scoped searches match it
        # via the ``user_id is null`` branch of the filter expression.
    )

    # ------------------------------------------------------------------
    # Demonstrate the isolation contract DIRECTLY against Knowledge.
    #
    # On Milvus Lite the retrieved content is blank (see the caveat in the
    # module docstring), so we assert on result COUNT. The admin view is
    # the whole corpus; each scoped view drops exactly the other user's
    # private chunk.
    # ------------------------------------------------------------------
    print("\n=== Direct asearch tests ===\n")

    admin_view = await knowledge.asearch(query="salary", user_id=None)
    print(f"Admin (user_id=None) -> {len(admin_view)} results (whole corpus)")

    alice_view = await knowledge.asearch(query="salary", user_id="alice")
    print(f"Alice (scoped)        -> {len(alice_view)} results (own + shared)")

    bob_view = await knowledge.asearch(query="salary", user_id="bob")
    print(f"Bob (scoped)          -> {len(bob_view)} results (own + shared)")

    # The canonical isolation assertions: admin sees all three uploads,
    # while each scoped user sees exactly two (their own chunk plus the
    # shared holidays doc) — the other user's private chunk is filtered out.
    assert len(admin_view) == 3, (
        f"Admin should see the whole corpus, got {len(admin_view)}"
    )
    assert len(alice_view) == len(admin_view) - 1, (
        "Isolation broken: Alice's scoped view should drop exactly Bob's chunk"
    )
    assert len(bob_view) == len(admin_view) - 1, (
        "Isolation broken: Bob's scoped view should drop exactly Alice's chunk"
    )
    print("  isolation holds: neither user's scope includes the other's chunk")

    # Bob asking about holidays still reaches the shared bucket.
    bob_holidays = await knowledge.asearch(
        query="When is the company closed?", user_id="bob"
    )
    print(f"\nBob asks about holidays -> {len(bob_holidays)} results")
    assert bob_holidays, "Bob should still see the shared holidays doc"

    # ------------------------------------------------------------------
    # End-to-end: an Agent doing RAG-as-Alice never sees Bob's chunks.
    # The ``user_id`` on the Agent flows into ``run_context.user_id``,
    # which ``KnowledgeTools.search_knowledge`` reads and forwards to
    # ``knowledge.search``. In a real deployment this comes from
    # ``get_scoped_user_id(request)`` (the JWT sub).
    # ------------------------------------------------------------------
    print("\n=== Agent-mediated test ===\n")

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

    response = await alice_agent.arun("What is Bob's salary?")
    print("Alice's agent on 'What is Bob's salary?':")
    print(response.content)

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
