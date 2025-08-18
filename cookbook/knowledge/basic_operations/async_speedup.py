"""This cookbook shows how to add content from a GCS bucket to the knowledge base.
1. Run: `python cookbook/agent_concepts/knowledge/12_from_gcs.py` to run the cookbook
"""

import asyncio
import time

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.pdf_reader import PDFReader
from agno.vectordb.pgvector import PgVector

chunk_size = 500


vector_db = PgVector(
    table_name="vectors", db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"
)
knowledge = Knowledge(vector_db=vector_db)
start_time = time.time()
asyncio.run(
    knowledge.add_content(
        name="Recipes",
        path="storage/manual.pdf",
        # path="cookbook_v2/knowledge/data/filters/cv_1.pdf",
        reader=PDFReader(chunk=True, chunk_size=chunk_size),
        upsert=False,
    )
)
end_time = time.time()

print(f"Time taken without batch: {end_time - start_time} seconds")
vector_db.delete()
