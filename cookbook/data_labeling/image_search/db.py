"""
Shared Storage and Knowledge

PostgresDb is used by:
  - Knowledge.contents_db (gallery list, content metadata, status)
  - Workflow.db          (background runs for the Reindex button)

PgVector is used as the vector store. We pick Postgres for both layers
so:
  - Keyword search is real lexical FTS (to_tsvector + to_tsquery), with
    prefix matching on — "ani" matches "animal" (the `anim` lexeme has
    `ani` as a prefix), and "mount" matches "mountain". Stemming still
    keeps "car" / "cars" together without lumping in "streetcar".
  - List metadata (tags, subjects) round-trips through JSONB as native
    arrays, not JSON-encoded strings.

Knowledge is used by:
  - The ingest workflow's executor (writes)
  - AgentOS's /knowledge/* routes (reads)
"""

from agno.db.postgres import PostgresDb
from agno.knowledge.embedder.google import GeminiEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector, SearchType
from settings import (
    DB_URL,
    EMBEDDER_MODEL_ID,
    KNOWLEDGE_NAME,
    KNOWLEDGE_TABLE,
    VECTOR_TABLE,
)

_db: PostgresDb | None = None
_knowledge: Knowledge | None = None


def get_db() -> PostgresDb:
    global _db
    if _db is None:
        _db = PostgresDb(db_url=DB_URL, knowledge_table=KNOWLEDGE_TABLE)
    return _db


def get_knowledge() -> Knowledge:
    global _knowledge
    if _knowledge is None:
        _knowledge = Knowledge(
            name=KNOWLEDGE_NAME,
            contents_db=get_db(),
            vector_db=PgVector(
                db_url=DB_URL,
                table_name=VECTOR_TABLE,
                search_type=SearchType.hybrid,
                embedder=GeminiEmbedder(id=EMBEDDER_MODEL_ID),
                prefix_match=True,
            ),
        )
    return _knowledge
