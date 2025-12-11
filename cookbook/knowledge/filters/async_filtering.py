import asyncio
import os

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.filters import IN, OR
from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.pdf_reader import PDFReader
from agno.utils.media import (
    SampleDataFileExtension,
    download_knowledge_filters_sample_data,
)
from agno.vectordb.pgvector import PgVector
from agno.vectordb.search import SearchType

# Download all sample CVs and get their paths
downloaded_cv_paths = download_knowledge_filters_sample_data(
    num_files=5, file_extension=SampleDataFileExtension.DOCX
)

# Clean up old databases
if os.path.exists("tmp/knowledge_contents.db"):
    os.remove("tmp/knowledge_contents.db")
db = PostgresDb(
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    knowledge_table="knowledge_contents",
)


# Initialize Vector Database
vector_db = PgVector(
    table_name="CVs",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    search_type=SearchType.hybrid,
)

# Step 1: Initialize knowledge base with documents and metadata
# ------------------------------------------------------------------------------
# When initializing the knowledge base, we can attach metadata that will be used for filtering
# This metadata can include user IDs, document types, dates, or any other attributes

knowledge = Knowledge(
    name="Async Filtering",
    vector_db=vector_db,
    contents_db=db,
)

# asyncio.run(
#     knowledge.add_contents_async(
#         [
#             {
#                 "path": downloaded_cv_paths[0],
#                 "metadata": {
#                     "user_id": "jordan_mitchell",
#                     "document_type": "cv",
#                     "year": 2025,
#                 },
#             },
#             {
#                 "path": downloaded_cv_paths[1],
#                 "metadata": {
#                     "user_id": "taylor_brooks",
#                     "document_type": "cv",
#                     "year": 2025,
#                 },
#             },
#             {
#                 "path": downloaded_cv_paths[2],
#                 "metadata": {
#                     "user_id": "morgan_lee",
#                     "document_type": "cv",
#                     "year": 2025,
#                 },
#             },
#             {
#                 "path": downloaded_cv_paths[3],
#                 "metadata": {
#                     "user_id": "casey_jordan",
#                     "document_type": "cv",
#                     "year": 2025,
#                 },
#             },
#             {
#                 "path": downloaded_cv_paths[4],
#                 "metadata": {
#                     "user_id": "alex_rivera",
#                     "document_type": "cv",
#                     "year": 2025,
#                 },
#             },
#         ],
#     )
# )

# asyncio.run(
#     knowledge.add_content_async(
#         name="Manual1",
#         path="cookbook/knowledge/testing_resources/manta_manual.pdf",
#         metadata={"user_tag": "manuals", "type": "hobbies"},
#         skip_if_exists=True,
#     ))


# asyncio.run(
#     knowledge.add_content_async(
#         name="Manual1",
#         path="cookbook/knowledge/testing_resources/AllClinicFAQs.md",
#         metadata={"clinic_site": "all_clinics"},
#         skip_if_exists=True,
#     ))

# asyncio.run(
#     knowledge.add_content_async(
#         name="Manual1",
#         path="cookbook/knowledge/testing_resources/BerkeleyFAQs.md",
#         metadata={"clinic_site": "berkeley"},
#         skip_if_exists=True,
#     ))

my_custom_reader = PDFReader(
    name="my_custom_reader",
    chunk_size=15,
    chunking_strategy=FixedSizeChunking(chunk_size=10, overlap=9),
)

custom_knowledge = Knowledge(
    name="Custom Knowledge",
    vector_db=vector_db,
    contents_db=db,
    readers=[my_custom_reader],
)

asyncio.run(
    custom_knowledge.add_content_async(
        name="Manual1",
        path="cookbook/knowledge/testing_resources/manta_manual.pdf",
        metadata={"user_tag": "manuals", "type": "hobbies"},
        skip_if_exists=True,
        reader=my_custom_reader,
    )
)

print(custom_knowledge.readers)
# Step 2: Query the knowledge base with different filter combinations
# ------------------------------------------------------------------------------

# Option 1: Filters on the Agent
# Initialize the Agent with the knowledge base and filters
# agent = Agent(
#     db=db,
#     knowledge=knowledge,
#     search_knowledge=True,
# )

# if __name__ == "__main__":
#     # Query for Jordan Mitchell's experience and skills
#     # asyncio.run(
#     #     agent.aprint_response(
#     #         "Search the knowledge base for the candidate's experience and skills",
#     #         knowledge_filters={"user_id": "jordan_mitchell"},
#     #         markdown=True,
#     #     )
#     # )

#     kdb_clinic_site = "berkeley"
#     asyncio.run(
#         agent.aprint_response(
#             "What is the fax number?",
#             knowledge_filters=[OR(IN("clinic_site", [kdb_clinic_site]), IN("clinic_site", ["all_clinics"]))],
#             markdown=True,
#         )
#     )
