"""
Qdrant Hybrid Search for Offline Mode
================================================

Demonstrates how to use Qdrant hybrid search in offline/air-gapped environments.

Prerequisites:
- Ollama must be downloaded and running: https://ollama.com/download
- Run ollama pull llama3.2
- Run `uv pip install sentence-transformers ollama` to install dependencies.
"""

import os
import shutil

from agno.agent import Agent
from agno.knowledge.embedder.sentence_transformer import SentenceTransformerEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.ollama import Ollama
from agno.vectordb.qdrant import Qdrant
from agno.vectordb.search import SearchType

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MODEL_CACHE_DIR = os.path.join(os.getcwd(), "tmp", "qdrant_models")

print(f"\nModel cache directory: {MODEL_CACHE_DIR}")

# ---------------------------------------------------------------------------
# Step 1: Pre-cache the model (run with internet access once)
# ---------------------------------------------------------------------------
print("\n[Step 1] Pre-caching BM25 model (requires internet)...")
print("This step downloads the model to the cache directory.")

try:
    # Pre-cache SentenceTransformer model
    embedder = SentenceTransformerEmbedder(
        id="sentence-transformers/all-MiniLM-L6-v2", dimensions=384
    )

    # Pre-cache BM25 model
    cache_db = Qdrant(
        collection="cache_setup",
        url="http://localhost:6333",
        embedder=embedder,
        search_type=SearchType.hybrid,
        fastembed_kwargs={
            "cache_dir": MODEL_CACHE_DIR,
        },
    )
    print(f"  SUCCESS: Model cached at {MODEL_CACHE_DIR}")

except Exception as e:
    print(f"  ERROR during model caching: {e}")
    print("\nNote: You need internet access for initial model caching.")
    exit(1)

# ---------------------------------------------------------------------------
# Step 2: Use cached model in offline mode
# ---------------------------------------------------------------------------
print("\n[Step 2] Using cached model in offline mode...")
print("This step requires NO internet access to verify true offline operation.")
print("\nPlease disconnect from the internet now.")

# Ask user confirmation
while True:
    user_input = input("\nIs your internet connection OFF? (Y/N): ").strip().upper()
    if user_input in ["Y", "N"]:
        break
    print("Please enter Y or N")

if user_input == "N":
    print("\n" + "=" * 60)
    print("SETUP INCOMPLETE")
    print("=" * 60)
    print("\nPlease disconnect from the internet and run this script again.")
    print("This ensures you experience true offline mode operation.")
    print("=" * 60)
    exit(0)

try:
    offline_db = Qdrant(
        collection="offline_demo",
        url="http://localhost:6333",
        embedder=embedder,
        search_type=SearchType.hybrid,
        fastembed_kwargs={
            "cache_dir": MODEL_CACHE_DIR,
            "local_files_only": True,
        },
    )

except ValueError as e:
    if "Could not load model" in str(e):
        print("\n  ERROR: Model not found in cache")
        exit(1)
    raise

# ---------------------------------------------------------------------------
# Step 3: Load documents and test search
# ---------------------------------------------------------------------------
print("\n[Step 3] Loading documents and testing hybrid search...")

knowledge = Knowledge(vector_db=offline_db)

documents = [
    "Agno is an open-source framework for building agentic AI applications.",
    "Hybrid search combines semantic search with keyword matching.",
    "Air-gapped systems are isolated networks without internet access.",
    "BM25 is a ranking function used in information retrieval.",
    "Qdrant supports hybrid search with dense and sparse vectors.",
]

for doc in documents:
    knowledge.insert(text_content=doc)

agent = Agent(
    model=Ollama(id="llama3.2", host="http://localhost:11434"),
    knowledge=knowledge,
    search_knowledge=True,
    instructions=["Use the knowledge base to answer questions accurately."],
)

agent.print_response("What is hybrid search?", markdown=True)

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

cache_db.drop()
offline_db.drop()

# Remove model cache directory
if os.path.exists(MODEL_CACHE_DIR):
    shutil.rmtree(MODEL_CACHE_DIR)

qdrant_data_dir = os.path.join(os.getcwd(), "qdrant_data")
if os.path.exists(qdrant_data_dir):
    shutil.rmtree(qdrant_data_dir)
