"""
Shared Storage and Knowledge

SqliteDb is used by:
  - Knowledge.contents_db (gallery list, content metadata, status)
  - Workflow.db          (background runs for the Reindex button)

Knowledge is used by:
  - The ingest workflow's executor (writes)
  - AgentOS's /knowledge/* routes (reads)
"""

from agno.db.sqlite import SqliteDb
from agno.knowledge.embedder.google import GeminiEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.chroma import ChromaDb
from settings import (
    CHROMA_COLLECTION,
    CHROMA_PATH,
    EMBEDDER_MODEL_ID,
    KNOWLEDGE_NAME,
    SQLITE_PATH,
)

_db: SqliteDb | None = None
_knowledge: Knowledge | None = None


def get_db() -> SqliteDb:
    global _db
    if _db is None:
        _db = SqliteDb(db_file=str(SQLITE_PATH))
    return _db


def get_knowledge() -> Knowledge:
    global _knowledge
    if _knowledge is None:
        _knowledge = Knowledge(
            name=KNOWLEDGE_NAME,
            contents_db=get_db(),
            vector_db=ChromaDb(
                collection=CHROMA_COLLECTION,
                persistent_client=True,
                path=str(CHROMA_PATH),
                embedder=GeminiEmbedder(id=EMBEDDER_MODEL_ID),
            ),
        )
    return _knowledge
