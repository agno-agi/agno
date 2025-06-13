from agno.document import Document
from agno.document.local_document_store import LocalDocumentStore
from agno.knowledge.knowledge_base import KnowledgeBase
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

document_store = LocalDocumentStore(
    name="local_document_store",
    description="Local document store",
    storage_path="tmp/documents",
)

vector_store = PgVector(
    table_name="pdf_documents",
    # Can inspect database via psql e.g. "psql -h localhost -p 5432 -U ai -d ai"
    db_url=db_url,
)

# Create knowledge base
kb = KnowledgeBase(
    name="My Knowledge Base",
    description="A simple knowledge base",
    document_store=document_store,
)

# Add a document
doc = Document(content="Hello worlds", name="greetings")
doc_id = kb.add_document(doc)

# Retrieve documents
all_docs = kb.get_all_documents()
specific_doc = kb.get_document_by_id(doc_id)

print(specific_doc.content)

deleted = kb.delete_document(document_id=doc_id)
print(deleted)

specific_doc = kb.get_document_by_id(doc_id)
print(specific_doc)
