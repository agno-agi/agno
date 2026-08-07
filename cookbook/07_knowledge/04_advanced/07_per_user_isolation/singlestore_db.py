"""
Per-User Knowledge Isolation with SingleStore
=============================================
Each user gets a private view of one shared knowledge base. Documents
uploaded with a user_id are visible only to that user; documents uploaded
without one are shared with everyone.

SingleStore stores the owner in a nullable user_id column and scopes reads
with WHERE user_id = X OR user_id IS NULL.

- Search as Alice: her chunks plus shared content, never Bob's
- Search as Bob: his chunks plus shared content, never Alice's
- Search with user_id=None: admin view, sees everything

Requirements: ./cookbook/scripts/run_singlestore.sh, the SINGLESTORE_HOST /
_PORT / _USERNAME / _PASSWORD / _DATABASE env vars and OPENAI_API_KEY
Run: python cookbook/07_knowledge/04_advanced/07_per_user_isolation/singlestore_db.py
"""

import asyncio
from os import getenv
from pathlib import Path
from urllib.parse import quote_plus

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.singlestore import SingleStore
from sqlalchemy.engine import create_engine

USERNAME = getenv("SINGLESTORE_USERNAME")
PASSWORD = getenv("SINGLESTORE_PASSWORD")
HOST = getenv("SINGLESTORE_HOST")
PORT = getenv("SINGLESTORE_PORT")
DATABASE = getenv("SINGLESTORE_DATABASE")


def _write_temp_doc(name: str, body: str) -> str:
    """Write a tiny text file we can ingest. Returns the absolute path."""
    p = Path(f"/tmp/{name}")
    p.write_text(body)
    return str(p)


def _build_engine():
    # quote_plus the password so special characters survive the URL.
    db_url = f"mysql+pymysql://{USERNAME}:{quote_plus(PASSWORD or '')}@{HOST}:{PORT}/{DATABASE}?charset=utf8mb4"
    return create_engine(db_url)


async def main() -> None:
    vector_db = SingleStore(
        collection="per_user_isolation_demo",
        schema=DATABASE,
        db_engine=_build_engine(),
    )

    # Start clean; drop() raises if the table does not exist yet.
    try:
        vector_db.drop()
    except Exception:
        pass
    vector_db.create()

    knowledge = Knowledge(
        name="per_user_demo",
        description="Per-user RAG isolation demo (SingleStore)",
        vector_db=vector_db,
    )

    # Alice and Bob upload private docs; the last upload has no user_id,
    # which makes it shared / org-wide content.
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
    )

    print("\n=== Direct asearch tests ===\n")

    alice_salary = await knowledge.asearch(
        query="What is Alice's salary?", user_id="alice"
    )
    print(f"Alice asks about Alice's salary -> {len(alice_salary)} results")
    for d in alice_salary:
        print(f"  - {d.content[:80]}")
    assert alice_salary, "expected Alice's own results, got none"

    alice_about_bob = await knowledge.asearch(
        query="What is Bob's salary?", user_id="alice"
    )
    print(f"\nAlice asks about Bob's salary -> {len(alice_about_bob)} results")
    for d in alice_about_bob:
        print(f"  - {d.content[:80]}")
    # user_id stays internal to this backend, so verify isolation by content.
    bob_leak = [d for d in alice_about_bob if "215,000" in d.content]
    assert not bob_leak, "Isolation broken: Alice's retrieval surfaced Bob's salary"
    print("  isolation holds: Bob's salary is NOT visible to Alice")

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

    response = await alice_agent.arun("What is Bob's salary?")
    print("Alice's agent on 'What is Bob's salary?':")
    print(response.content)

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
