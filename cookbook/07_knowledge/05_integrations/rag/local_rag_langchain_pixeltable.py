"""
Local RAG with LangChain and Pixeltable
========================================

Pixeltable (https://github.com/pixeltable/pixeltable) is a multimodal data
layer. An embedding index on a table stays up to date as rows change, so
there is no separate vector database to keep in sync.

This example writes chunks with the LangChain adapter ``PixeltableVectorStore``
(``pip install langchain-pixeltable``) and searches them from an Agno agent
through ``LangChainVectorDb``. Embeddings are local sentence-transformers
(``sentence-transformers/all-MiniLM-L6-v2``). No embedding API key and no
vector database server are required. Pixeltable stores the table in an
embedded database under the Pixeltable home directory.

Setup:
    uv pip install langchain-pixeltable langchain-huggingface langchain-text-splitters sentence-transformers ollama openai

Importing ``agno.models.ollama`` also imports Agno's OpenAI client, so
``openai`` has to be installed even when the agent uses Ollama.

The agent model is Ollama ``qwen2.5:latest``, matching the Qdrant LangChain
example. Retrieval itself does not need Ollama. To generate an answer:

    ollama pull qwen2.5:latest

Run:
    .venvs/demo/bin/python cookbook/07_knowledge/05_integrations/rag/local_rag_langchain_pixeltable.py
"""

import httpx
import pixeltable as pxt
from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.models.ollama import Ollama
from agno.vectordb.langchaindb import LangChainVectorDb
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_pixeltable import PixeltableVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

# Notes kept in the example so a run does not depend on a live web page.
# Any LangChain loader can replace this document.
source = """
Pixeltable is a multimodal data layer. A table can hold text, images, video,
and audio together. An embedding index on a column stays up to date when rows
are inserted, updated, or deleted, so the vectors do not drift from the rows
they describe.

The langchain-pixeltable package exposes that table as a LangChain vector
store. PixeltableVectorStore writes each chunk into the table and adds an
embedding index on the stored vectors. A similarity search embeds the query
and ranks rows with Pixeltable's similarity expression.

Agno searches the store through LangChainVectorDb. Wrap the Pixeltable
retriever in Knowledge and give that knowledge base to an Agent with
search_knowledge enabled. The agent calls the knowledge search tool, and the
tool invokes the Pixeltable retriever.

This stack runs locally. sentence-transformers computes embeddings on the
machine, and Pixeltable stores the table in an embedded Postgres database.
No embedding API key and no standalone vector database server are required.
"""

table_name = "agno_rag/docs"
notes = Document(page_content=source, metadata={"source": "pixeltable-notes"})
chunks = RecursiveCharacterTextSplitter(
    chunk_size=500, chunk_overlap=40
).split_documents([notes])
embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")

# Replace the table on each run so chunks are not appended twice.
# Slash paths are the current Pixeltable name form. The adapter creates the
# table and its embedding index on the first insert.
pxt.drop_table(table_name, if_not_exists="ignore")
pxt.create_dir("agno_rag", if_exists="ignore")

vector_store = PixeltableVectorStore(table_name=table_name, embedding=embeddings)
vector_store.add_documents(chunks)
retriever = vector_store.as_retriever(search_kwargs={"k": 3})

# ---------------------------------------------------------------------------
# Create Knowledge Base
# ---------------------------------------------------------------------------

# exists() is not implemented on the LangChain wrapper. Constructing Knowledge
# logs that warning and leaves the Pixeltable table in place.
knowledge = Knowledge(
    name="Pixeltable notes",
    description="Local notes stored in a Pixeltable embedding index",
    vector_db=LangChainVectorDb(knowledge_retriever=retriever),
    max_results=3,
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Ollama(id="qwen2.5:latest"),
    knowledge=knowledge,
    description="Answer the user question from the knowledge base",
    markdown=True,
    search_knowledge=True,
)

user_query = "How does an Agno agent search documents stored in Pixeltable?"


def ollama_is_running() -> bool:
    try:
        response = httpx.get("http://127.0.0.1:11434/api/tags", timeout=2.0)
    except httpx.HTTPError:
        return False
    return response.is_success


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Retrieved documents")
    retrieved = knowledge.search(query=user_query, max_results=3)
    if not retrieved:
        print("No documents retrieved.")
        raise SystemExit(1)

    for index, document in enumerate(retrieved, start=1):
        preview = " ".join(document.content.split())
        print(f"[{index}] {preview}")

    if not ollama_is_running():
        print("Ollama is not running at http://127.0.0.1:11434.")
        print(
            "Retrieval above does not need a model. Start Ollama and pull qwen2.5:latest to generate an answer."
        )
    else:
        agent.print_response(user_query, stream=True)
