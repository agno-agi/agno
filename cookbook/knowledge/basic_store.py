from agno.agent import Agent
from agno.document.local_store import LocalDocumentStore
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.source import DocumentV2

# from agno.document.s3_document_store import S3DocumentStore
from agno.vectordb.pgvector import PgVector

# This is where we will store our documents
document_store = LocalDocumentStore(
    name="local_document_store",
    description="Local document store",
    storage_path="tmp/documents",
)

# This is a source of user documents
# document_seed_store = S3DocumentStore(
#     name="local_document_store_seed",
#     description="Instance of document store where existing documents are pulled from",
#     read_from_store=True,
#     copy_to_store=False
# )
document_seed_store = None

# Create Knowledge Instance
knowledge = Knowledge(
    name="My Knowledge Base",
    description="Agno 2.0 Knowledge Implementation",
    document_store=document_store,
    vector_store=PgVector(
        table_name="vectors", db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"
    ),
)

# This will add a document to the document store

knowledge.load()
knowledge.add_documents(
    DocumentV2(
        name="CV1",
        paths=["tmp/cv_1.pdf"],
        metadata={"user_tag": "Engineering candidates"},
    )
)
