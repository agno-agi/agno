from agno.knowledge.knowledge_base import KnowledgeBase
from agno.document import Document
from agno.document.local_document_store import LocalDocumentStore
from agno.vectordb.pgvector import PgVector
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

document_store = LocalDocumentStore(
    name="local_document_store",
    description="Local document store",
    storage_path="tmp/documents"
)

vector_store=PgVector(
        table_name="vectors",
        db_url=db_url,
    )

# Create knowledge base
kb = KnowledgeBase(
    name="My Knowledge Base", 
    description="Agno 2.0 Knowledge Base Implementation",
    document_store=document_store,
    vector_store=vector_store
)

# Add a document
doc = Document(content="Hello worlds", name="greetings")
doc_id = kb.add_document(doc)
dc = kb.add_document_by_path("tmp/cv_1.pdf")

# Retrieve documents
# all_docs = kb.get_all_documents()
# specific_doc = kb.get_document_by_id(doc_id)

# print(specific_doc.content)

# deleted = kb.delete_document(document_id=doc_id)
# print(deleted)

# specific_doc = kb.get_document_by_id(doc_id)
# print(specific_doc)