from agno.db.postgres.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
contents_db = PostgresDb(
    db_url, id="basic_knowledge_db", knowledge_table="basic_knowledge"
)

knowledge = Knowledge(
    name="Basic Knowledge",
    description="A basic knowledge base",
    vector_db=PgVector(db_url=db_url, table_name="basic_vectors"),
    contents_db=contents_db,
)
