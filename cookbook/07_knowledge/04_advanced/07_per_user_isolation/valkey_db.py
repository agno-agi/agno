"""
Per-User Knowledge Isolation with Valkey
========================================
Give each user a private view of one shared knowledge base. Documents a user
uploads are visible only to them; documents uploaded with no user are shared
with everyone, and an admin (no user id) sees all of it.

Valkey does this by storing the owner as a TAG field and filtering on it
inside FT.SEARCH itself, storing chunks with no owner under a shared
sentinel tag. This example drives the vector db API directly; agent-mediated
per-user retrieval arrives with the Knowledge-level isolation release.

Setup: ./cookbook/scripts/run_valkey.sh
"""

import asyncio

from agno.knowledge.document.base import Document
from agno.vectordb.search import SearchType
from agno.vectordb.valkey import ValkeyDB


def _doc(name: str, body: str) -> Document:
    return Document(name=name, content=body)


async def main() -> None:
    vector_db = ValkeyDB(
        index_name="per_user_isolation_demo",
        host="localhost",
        port=6379,
        search_type=SearchType.vector,
    )
    try:
        await vector_db.async_drop()
    except Exception:
        pass
    await vector_db.async_create()

    await vector_db.async_insert(
        content_hash="alice_salary",
        documents=[
            _doc(
                "alice_salary",
                "Alice's salary is $180,000. Reviewed annually in March.",
            )
        ],
        user_id="alice",
    )
    await vector_db.async_insert(
        content_hash="bob_salary",
        documents=[
            _doc("bob_salary", "Bob's salary is $215,000. Reviewed annually in June.")
        ],
        user_id="bob",
    )
    await vector_db.async_insert(
        content_hash="company_holidays",
        documents=[
            _doc(
                "company_holidays",
                "The company is closed on January 1, July 4, and December 25.",
            )
        ],
    )

    print("\n=== Direct search tests ===\n")
    alice_salary = await vector_db.async_search(
        query="What is Alice's salary?", limit=10, user_id="alice"
    )
    print(f"Alice asks about Alice's salary -> {len(alice_salary)} results")
    for d in alice_salary:
        print(f"  - {d.content[:80]}")

    alice_about_bob = await vector_db.async_search(
        query="What is Bob's salary?", limit=10, user_id="alice"
    )
    print(f"\nAlice asks about Bob's salary -> {len(alice_about_bob)} results")
    for d in alice_about_bob:
        print(f"  - {d.content[:80]}")
    # This backend keeps user_id internal (not surfaced in returned meta_data),
    # so verify isolation by content rather than by reading an owner off the row.
    bob_leak = [d for d in alice_about_bob if "215,000" in d.content]
    assert not bob_leak, "Isolation broken: Alice's retrieval surfaced Bob's salary"
    print("  isolation holds: Bob's salary is NOT visible to Alice")

    bob_holidays = await vector_db.async_search(
        query="When is the company closed?", limit=10, user_id="bob"
    )
    print(f"\nBob asks about holidays -> {len(bob_holidays)} results")
    for d in bob_holidays:
        print(f"  - {d.content[:80]}")

    admin_view = await vector_db.async_search(query="salary", limit=10, user_id=None)
    print(f"\nAdmin asks about salary (user_id=None) -> {len(admin_view)} results")
    for d in admin_view:
        print(f"  - {d.content[:80]}")

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
