"""
This example demonstrates using Weaviate as a vector database.

Installation:
    pip install weaviate-client

You can use either Weaviate Cloud or a local instance.

Weaviate Cloud Setup:
1. Create account at https://console.weaviate.cloud/
2. Create a cluster and copy the "REST endpoint" and "Admin" API Key. Then set environment variables:
    export WCD_URL="your-cluster-url" 
    export WCD_API_KEY="your-api-key"

Local Development Setup:
1. Install Docker from https://docs.docker.com/get-docker/
2. Run Weaviate locally:
    docker run -d \
        -p 8080:8080 \
        -p 50051:50051 \
        --name weaviate \
        cr.weaviate.io/semitechnologies/weaviate:1.28.4
   or use the script `cookbook/scripts/run_weviate.sh` to start a local instance.
3. Remember to set `local=True` on the Weaviate instantiation.
"""

from agno.document import Document
from agno.embedder.sentence_transformer import SentenceTransformerEmbedder
from agno.knowledge.document import DocumentKnowledgeBase
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.utils.log import set_log_level_to_debug
from agno.vectordb.search import SearchType
from agno.vectordb.weaviate import Distance, VectorIndex, Weaviate

embedder = SentenceTransformerEmbedder()

vector_db = Weaviate(
    collection="recipes",
    search_type=SearchType.hybrid,
    vector_index=VectorIndex.HNSW,
    distance=Distance.COSINE,
    embedder=embedder,
    local=True,  # Set to False if using Weaviate Cloud and True if using local instance
)
# Create knowledge base
knowledge_base = PDFUrlKnowledgeBase(
    urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
    vector_db=vector_db,
)

vector_db.drop()
set_log_level_to_debug()

knowledge_base.load(recreate=False, upsert=True)

print(
    "Knowledge base loaded with PDF content. Loading the same data again will not recreate it."
)
knowledge_base.load(recreate=False, upsert=True)

print("First example finished. Now dropping the knowledge base.")
vector_db.drop()

doc1 = Document(content="my first content", name="doc1")
doc1_modified = Document(content="my first content corrected", name="doc1")
doc2 = Document(content="my second content", name="doc2")

knowledge_base = DocumentKnowledgeBase(
    documents=[doc1, doc2],
    vector_db=vector_db,
)
knowledge_base_changed = DocumentKnowledgeBase(
    documents=[doc1_modified, doc2],
    vector_db=vector_db,
)

print("\n\nStart second example. Load initial data...")
knowledge_base.load(recreate=False, upsert=True)
print("\nNow uploading the changed data...")
knowledge_base_changed.load(recreate=False, upsert=True)
print("Example finished. Now dropping the knowledge base.")
vector_db.drop()
