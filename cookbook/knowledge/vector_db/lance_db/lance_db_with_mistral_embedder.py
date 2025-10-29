import asyncio

from agno.knowledge.embedder.mistral import MistralEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.pdf_reader import PDFReader
from agno.vectordb.lancedb import LanceDb, SearchType

embedder_mi = MistralEmbedder()

vector_db = LanceDb(
    uri="tmp/lancedb",
    table_name="documents",
    embedder=embedder_mi,
    search_type=SearchType.hybrid,
)

reader = PDFReader(
    chunk_size=1024,
)

knowledge = Knowledge(
    name="My Document Knowledge Base",
    vector_db=vector_db,
)


asyncio.run(
    knowledge.add_content_async(
        name="CV",
        path="cookbook/knowledge/testing_resources/cv_1.pdf",
        metadata={"user_tag": "Engineering Candidates"},
        reader=reader,
    )
)
