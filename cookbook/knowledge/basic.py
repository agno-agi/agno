from agno.knowledge.knowledge import Knowledge
from agno.document.local_document_store import LocalDocumentStore
from agno.vectordb.pgvector import PgVector
from agno.document import Document

document_store = LocalDocumentStore(
    name="local_document_store",
    description="Local document store",
    storage_path="tmp/documents",
    read_from_store=False,
    copy_to_store=True
)

document_seed_store = LocalDocumentStore(
    name="local_document_store_seed",
    description="Instance of document store where existing documents are pulled from",
    storage_path="tmp/seed_documents",
    read_from_store=True,
    copy_to_store=False
)


# Create Knowledge Instance
knowledge = Knowledge(
    name="My Knowledge Base", 
    description="Agno 2.0 Knowledge Implementation",
    document_store=document_store,
    vector_store=PgVector(
        table_name="vectors",
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"
    ),
    documents=[
        {
            "name": "LLMs Full",
            "source": "https://docs.agno.com/llms-full.txt",
            "metadata": {
                "user_tag": "Agno Documentation"
            }
        },
        {
            "name": "CV2",
            "source": "tmp/cv_2.pdf",
            "metadata": {
                "user_tag": "Engineering candidates"
            }
        },
        Document(
            name="CV2",
            content="This is a test document",
            meta_data={
                "user_tag": "Engineering candidates"
            }
        )
    ]
)

# Add a document
knowledge.load()
knowledge.load_documents({"paths": ["tmp/cv_2.pdf", "https://docs.agno.com/llms-full.txt"]}) #Need to figure out the DX for this
knowledge.load_documents(documentStore=document_seed_store)


# Remove documents
knowledge.remove_document(document_id="123456", remove_from_store=True)
knowledge.remove_all_documents(remove_from_store=True)

# Get documents
knowledge.get_document_by_id(document_id="123456")
knowledge.get_all_documents()
knowledge.get_documents_by_name(name="llms-full.txt")
knowledge.get_documents_by_metadata(metadata={"key": "value"})
