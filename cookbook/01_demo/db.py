"""Database configuration."""

from os import getenv

from agno.db.postgres import PostgresDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.vectordb.pgvector import PgVector, SearchType

db_url = getenv("DATABASE_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai")


def get_postgres_db(contents_table: str | None = None) -> PostgresDb:
    if contents_table is not None:
        return PostgresDb(id="demo-db", db_url=db_url, knowledge_table=contents_table)
    return PostgresDb(id="demo-db", db_url=db_url)


def create_knowledge(name: str, table_name: str) -> Knowledge:
    return Knowledge(
        name=name,
        vector_db=PgVector(
            db_url=db_url,
            table_name=table_name,
            search_type=SearchType.hybrid,
            embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        ),
        contents_db=get_postgres_db(contents_table=f"{table_name}_contents"),
        max_results=10,
    )
