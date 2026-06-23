"""Per-user knowledge isolation with LanceDB.

Same isolation contract as the pgvector cookbook in this directory, against
a different backend. The ``Knowledge.asearch(user_id=...)`` API is
identical — only the underlying primitive changes:

  * pgvector uses a B-tree-indexed ``user_id`` column with
    ``WHERE user_id = X OR user_id IS NULL``.

  * LanceDB uses a top-level ``user_id`` column on its Arrow table with
    ``.where("user_id = 'X' OR user_id IS NULL", prefilter=True)``. The
    ``prefilter=True`` flag is load-bearing: it makes the predicate run
    BEFORE LanceDB's ANN top-K, so the vector ranking only sees rows the
    caller is allowed to read. Without it the wrapper used to post-filter
    in Python AFTER ranking — which silently truncates results for any
    scoped query.

Three uploads, four scoped queries:

  1. Alice and Bob each upload private content.
  2. An admin uploads org-wide content (``user_id`` left ``None``).
  3. Alice asks about Alice — sees her chunk plus shared content.
  4. Alice asks about Bob — sees ZERO bob chunks (assertion below).
  5. Bob asks about holidays — sees the shared bucket.
  6. Admin (``user_id=None``) sees everything.

Prerequisites:

  * ``pip install lancedb pyarrow`` (no server to run; LanceDB is embedded).
  * ``OPENAI_API_KEY`` set in your environment (or swap the model below).

Run:

    python cookbook/07_knowledge/04_advanced/07_per_user_isolation/lancedb.py
"""

import asyncio
import shutil
from pathlib import Path

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.lancedb import LanceDb

DB_PATH = "/tmp/agno_per_user_isolation_lancedb"
TABLE_NAME = "per_user_isolation_demo"


def _write_temp_doc(name: str, body: str) -> str:
    """Write a tiny text file we can ingest. Returns the absolute path."""
    p = Path(f"/tmp/{name}")
    p.write_text(body)
    return str(p)


async def main() -> None:
    # ------------------------------------------------------------------
    # Wipe any previous on-disk state. If you ran an older version of
    # this cookbook (before LanceDB grew a ``user_id`` column), the
    # cached schema would lack that column and isolation would silently
    # collapse. In production you'd run a real migration; here we just
    # drop-and-reingest.
    # ------------------------------------------------------------------
    if Path(DB_PATH).exists():
        shutil.rmtree(DB_PATH)

    vector_db = LanceDb(uri=DB_PATH, table_name=TABLE_NAME)

    knowledge = Knowledge(
        name="per_user_demo",
        description="Per-user RAG isolation demo (LanceDB)",
        vector_db=vector_db,
    )

    # ------------------------------------------------------------------
    # Three uploads: Alice (private), Bob (private), Admin (shared).
    # The ``user_id`` kwarg on ``ainsert`` flows through to the LanceDB
    # backend, which writes it to the dedicated ``user_id`` column. The
    # API call is identical to pgvector — see the sibling cookbook.
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
        # LanceDB stores NULL in the column; scoped queries match it via
        # ``user_id = caller OR user_id IS NULL``.
    )

    # ------------------------------------------------------------------
    # Demonstrate the isolation contract DIRECTLY against Knowledge.
    # The result counts tell the story; ``Document`` doesn't carry the
    # owner back (the column is internal to the backend), so we don't
    # print per-chunk ownership — the assertion is what matters.
    # ------------------------------------------------------------------
    print("\n=== Direct asearch tests ===\n")

    alice_salary = await knowledge.asearch(
        query="What is Alice's salary?", user_id="alice"
    )
    print(f"Alice asks about Alice's salary -> {len(alice_salary)} results")
    for d in alice_salary:
        print(f"  - {d.content[:80]}")

    alice_about_bob = await knowledge.asearch(
        query="What is Bob's salary?", user_id="alice"
    )
    print(f"\nAlice asks about Bob's salary -> {len(alice_about_bob)} results")
    for d in alice_about_bob:
        print(f"  - {d.content[:80]}")
    # The canonical isolation assertion: Bob's content must never surface
    # in Alice's retrieval, no matter how relevant it is to her query.
    bob_phrases = ["Bob's salary", "$215"]
    for d in alice_about_bob:
        for phrase in bob_phrases:
            assert phrase not in d.content, (
                f"Isolation broken: Alice's retrieval surfaced Bob's chunk "
                f"(matched {phrase!r}): {d.content!r}"
            )
    print("  isolation holds: Bob's chunks are NOT visible to Alice")

    bob_holidays = await knowledge.asearch(
        query="When is the company closed?", user_id="bob"
    )
    print(f"\nBob asks about holidays -> {len(bob_holidays)} results")
    for d in bob_holidays:
        print(f"  - {d.content[:80]}")

    admin_view = await knowledge.asearch(query="salary", user_id=None)
    print(f"\nAdmin asks about salary (user_id=None) -> {len(admin_view)} results")
    for d in admin_view:
        print(f"  - {d.content[:80]}")

    # ------------------------------------------------------------------
    # End-to-end: an Agent doing RAG-as-Alice never sees Bob's chunks.
    # The ``user_id`` on the Agent flows into ``run_context.user_id``,
    # which is what ``KnowledgeTools.search_knowledge`` reads and forwards
    # to ``knowledge.search``. In a real deployment this comes from
    # ``get_scoped_user_id(request)`` (the JWT sub).
    # ------------------------------------------------------------------
    print("\n=== Agent-mediated test ===\n")

    alice_agent = Agent(
        name="Alice's Assistant",
        model=OpenAIResponses(id="gpt-5.4"),
        knowledge=knowledge,
        user_id="alice",
        instructions=[
            "Answer questions using ONLY the knowledge you can retrieve.",
            "If you don't know, say so — do not invent salary figures.",
        ],
        markdown=True,
    )

    response = await alice_agent.arun("What is Bob's salary?")
    print("Alice's agent on 'What is Bob's salary?':")
    print(response.content)

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
