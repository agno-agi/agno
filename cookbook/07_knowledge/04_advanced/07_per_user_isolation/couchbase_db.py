"""
Per-User Isolation: Couchbase
=============================
Each user gets a private view of one shared knowledge base. Documents
uploaded with a user_id are visible only to that user; documents uploaded
without one are shared with everyone.

Couchbase stores the owner in a keyword-indexed FTS user_id field; shared chunks
carry a __shared__ sentinel because FTS has no is-missing predicate.

- Search as Alice: her chunks plus shared content, never Bob's
- Search as Bob: his chunks plus shared content, never Alice's
- Search with user_id=None: admin view, sees everything

Requirements:
- ./cookbook/scripts/run_couchbase.sh
- uv pip install couchbase
- OPENAI_API_KEY
"""

import asyncio
from os import getenv
from typing import List

from agno.agent import Agent
from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.couchbase import CouchbaseSearch
from couchbase.auth import PasswordAuthenticator
from couchbase.management.search import SearchIndex
from couchbase.options import ClusterOptions

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

ALICE_SALARY = "Alice's salary is $180,000. Reviewed annually in March."
BOB_SALARY = "Bob's salary is $215,000. Reviewed annually in June."
HOLIDAYS = "The company is closed on January 1, July 4, and December 25."

# Fallbacks match ./cookbook/scripts/run_couchbase.sh.
CB_USER = getenv("COUCHBASE_USER", "Administrator")
CB_PASS = getenv("COUCHBASE_PASSWORD", "password")
CB_CONN = getenv("COUCHBASE_CONNECTION_STRING", "couchbase://localhost")

BUCKET = "per_user_demo"
SCOPE = "iso_scope"
COLLECTION = "iso_collection"
INDEX = "iso_index"
DIMS = 1536  # text-embedding-3-small


def search_index_def() -> SearchIndex:
    """FTS vector index over content, the keyword user_id field and the embedding."""
    return SearchIndex(
        name=INDEX,
        source_type="gocbcore",
        idx_type="fulltext-index",
        source_name=BUCKET,
        plan_params={"index_partitions": 1, "num_replicas": 0},
        params={
            "doc_config": {
                "docid_prefix_delim": "",
                "docid_regexp": "",
                "mode": "scope.collection.type_field",
                "type_field": "type",
            },
            "mapping": {
                "default_analyzer": "standard",
                "default_datetime_parser": "dateTimeOptional",
                "index_dynamic": True,
                "store_dynamic": True,
                "default_mapping": {"dynamic": True, "enabled": False},
                "types": {
                    f"{SCOPE}.{COLLECTION}": {
                        "dynamic": False,
                        "enabled": True,
                        "properties": {
                            "content": {
                                "enabled": True,
                                "fields": [
                                    {
                                        "docvalues": True,
                                        "include_in_all": False,
                                        "include_term_vectors": False,
                                        "index": True,
                                        "name": "content",
                                        "store": True,
                                        "type": "text",
                                    }
                                ],
                            },
                            "user_id": {
                                "enabled": True,
                                "fields": [
                                    {
                                        "docvalues": True,
                                        "include_in_all": False,
                                        "include_term_vectors": False,
                                        "index": True,
                                        "name": "user_id",
                                        "store": True,
                                        "analyzer": "keyword",
                                        "type": "text",
                                    }
                                ],
                            },
                            "embedding": {
                                "enabled": True,
                                "dynamic": False,
                                "fields": [
                                    {
                                        "vector_index_optimized_for": "recall",
                                        "docvalues": True,
                                        "dims": DIMS,
                                        "include_in_all": False,
                                        "include_term_vectors": False,
                                        "index": True,
                                        "name": "embedding",
                                        "similarity": "dot_product",
                                        "store": True,
                                        "type": "vector",
                                    }
                                ],
                            },
                        },
                    }
                },
            },
        },
    )


def show(label: str, results: List[Document]) -> None:
    """Print one search result set."""
    print(f"{label} -> {len(results)} results")
    for d in results:
        print(f"  - {d.content[:80]}")
    print()


# ---------------------------------------------------------------------------
# Create Knowledge Base
# ---------------------------------------------------------------------------

vector_db = CouchbaseSearch(
    bucket_name=BUCKET,
    scope_name=SCOPE,
    collection_name=COLLECTION,
    couchbase_connection_string=CB_CONN,
    cluster_options=ClusterOptions(PasswordAuthenticator(CB_USER, CB_PASS)),
    search_index=search_index_def(),
    wait_until_index_ready=60,
)

# Start clean: documents from an earlier run would show up as extra results below.
if vector_db.exists():
    vector_db.drop()
vector_db.create()

knowledge = Knowledge(
    name="per_user_demo",
    description="Per-user RAG isolation demo (Couchbase)",
    vector_db=vector_db,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def main() -> None:
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
        # The last upload has no user_id, which makes it shared content.
        await knowledge.ainsert(
            name="company_holidays",
            text_content=HOLIDAYS,
        )

        # Give the FTS index a moment to ingest the new mutations.
        await asyncio.sleep(3)

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

        print("\n" + "=" * 60)
        print("AGENT-MEDIATED RETRIEVAL: the owner has to survive the handoff")
        print("=" * 60 + "\n")

        alice_agent = Agent(
            name="Alice's Assistant",
            model=OpenAIResponses(id="gpt-5.5"),
            knowledge=knowledge,
            search_knowledge=True,
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

        # Assert on what retrieval returned, not on the model's prose.
        retrieved = " ".join(
            item["content"]
            for ref in (response.references or [])
            for item in (ref.references or [])
            if isinstance(item, dict) and item.get("content")
        )
        assert retrieved, (
            "Retrieval returned no documents, so the isolation check below would pass on nothing"
        )
        assert "215,000" not in retrieved, (
            "Isolation broken: Alice's agent retrieved Bob's salary. The owner was "
            "dropped between the run context and the vector DB, so retrieval ran "
            "unscoped (user_id=None, the admin view)."
        )
        print("\nisolation holds: Bob's salary never reached Alice's agent")
        print("\nDone.")

    asyncio.run(main())
