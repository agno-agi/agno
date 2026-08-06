"""
Per-User Knowledge Isolation with OpenSearch
============================================
Each user gets a private view of one shared knowledge base. Documents
uploaded with a user_id are visible only to that user; documents uploaded
without one are shared with everyone.

OpenSearch stores the owner in a top-level user_id keyword field. Shared
chunks leave the field off, and a scoped read matches "term user_id" OR
"must_not exists user_id" - which is also why documents written before this
field existed keep showing up as shared content.

- Search as Alice: her chunks plus shared content, never Bob's
- Search as Bob: his chunks plus shared content, never Alice's
- Search with user_id=None: admin view, sees everything

Requirements: ./cookbook/scripts/run_opensearch.sh and OPENAI_API_KEY
Run: python cookbook/07_knowledge/04_advanced/07_per_user_isolation/opensearch_db.py
"""

import asyncio
import tempfile
from pathlib import Path

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.opensearch import OpenSearch

ALICE_SALARY = "Alice's salary is $180,000. Reviewed annually in March."
BOB_SALARY = "Bob's salary is $215,000. Reviewed annually in June."
HOLIDAYS = "The company is closed on January 1, July 4, and December 25."


def write_temp_doc(directory: str, name: str, body: str) -> str:
    """Write a tiny text file we can ingest. Returns the absolute path."""
    path = Path(directory) / name
    path.write_text(body)
    return str(path)


# ---------------------------------------------------------------------------
# Create the vector database and the knowledge base
# ---------------------------------------------------------------------------


async def create_knowledge() -> Knowledge:
    # Start clean: an index left over from another example would make its
    # documents look like shared content here.
    vector_db = OpenSearch(
        index_name="per_user_isolation_demo",
        url="http://localhost:9200",
    )
    vector_db.drop()
    await vector_db.async_create()

    return Knowledge(
        name="per_user_demo",
        description="Per-user RAG isolation demo (OpenSearch)",
        vector_db=vector_db,
    )


async def ingest(knowledge: Knowledge) -> None:
    # Alice and Bob upload private docs; the last upload has no user_id,
    # which makes it shared / org-wide content.
    workdir = tempfile.mkdtemp(prefix="agno_opensearch_isolation_")

    await knowledge.ainsert(
        path=write_temp_doc(workdir, "alice_salary.txt", ALICE_SALARY),
        name="alice_salary",
        user_id="alice",
    )

    await knowledge.ainsert(
        path=write_temp_doc(workdir, "bob_salary.txt", BOB_SALARY),
        name="bob_salary",
        user_id="bob",
    )

    await knowledge.ainsert(
        path=write_temp_doc(workdir, "company_holidays.txt", HOLIDAYS),
        name="company_holidays",
    )


# ---------------------------------------------------------------------------
# Run the isolation checks
# ---------------------------------------------------------------------------


async def main() -> None:
    knowledge = await create_knowledge()
    await ingest(knowledge)

    print("\n=== Direct asearch tests ===\n")

    alice_salary = await knowledge.asearch(
        query="What is Alice's salary?", user_id="alice"
    )
    print(f"Alice asks about Alice's salary -> {len(alice_salary)} results")
    for d in alice_salary:
        print(f"  - {d.content[:80]}")
    assert any("180,000" in d.content for d in alice_salary), (
        "Alice cannot retrieve her own document"
    )

    alice_about_bob = await knowledge.asearch(
        query="What is Bob's salary?", user_id="alice"
    )
    print(f"\nAlice asks about Bob's salary -> {len(alice_about_bob)} results")
    for d in alice_about_bob:
        print(f"  - {d.content[:80]}")
    # The owner is a field on the indexed document, not something the returned
    # Document carries, so isolation is verified by content.
    bob_leak = [d for d in alice_about_bob if "215,000" in d.content]
    assert not bob_leak, "Isolation broken: Alice's retrieval surfaced Bob's salary"
    print("  isolation holds: Bob's salary is NOT visible to Alice")

    bob_holidays = await knowledge.asearch(
        query="When is the company closed?", user_id="bob"
    )
    print(f"\nBob asks about holidays -> {len(bob_holidays)} results")
    for d in bob_holidays:
        print(f"  - {d.content[:80]}")
    assert any("January 1" in d.content for d in bob_holidays), (
        "Shared content is not reaching a scoped user"
    )

    admin_view = await knowledge.asearch(query="salary", user_id=None)
    print(f"\nAdmin asks about salary (user_id=None) -> {len(admin_view)} results")
    for d in admin_view:
        print(f"  - {d.content[:80]}")
    assert any("180,000" in d.content for d in admin_view) and any(
        "215,000" in d.content for d in admin_view
    ), "Admin view is missing one of the private documents"

    print("\n=== Agent-mediated test ===\n")

    # The agent's user_id flows into run_context and scopes its retrieval.
    alice_agent = Agent(
        name="Alice's Assistant",
        model=OpenAIResponses(id="gpt-5.5"),
        knowledge=knowledge,
        user_id="alice",
        search_knowledge=True,
        instructions=[
            "Answer questions using ONLY the knowledge you can retrieve.",
            "If you don't know, say so - do not invent salary figures.",
        ],
        markdown=True,
    )

    response = await alice_agent.arun("What is Bob's salary?")
    print("Alice's agent on 'What is Bob's salary?':")
    print(response.content)
    assert "215" not in response.content, (
        "Isolation broken: Bob's salary reached Alice's agent"
    )

    await knowledge.vector_db.async_close()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
