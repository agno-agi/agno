"""
LlamaIndex Vector DB
====================

Install dependencies:
- uv pip install llama-index-core llama-index-readers-file llama-index-embeddings-openai agno
"""

import asyncio
from pathlib import Path
from shutil import rmtree

import httpx
from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.vectordb.llamaindex.llamaindexdb import LlamaIndexVectorDb
from llama_index.core import SimpleDirectoryReader, StorageContext, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.retrievers import VectorIndexRetriever

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
data_dir = Path(__file__).parent.parent.parent.joinpath("wip", "data", "paul_graham")
source_url = "https://raw.githubusercontent.com/run-llama/llama_index/main/docs/docs/examples/data/paul_graham/paul_graham_essay.txt"


# ---------------------------------------------------------------------------
# Create Knowledge Base
# ---------------------------------------------------------------------------
def prepare_data() -> Path:
    if data_dir.is_dir():
        rmtree(path=data_dir, ignore_errors=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    file_path = data_dir.joinpath("paul_graham_essay.txt")
    response = httpx.get(source_url)
    if response.status_code == 200:
        with open(file_path, "wb") as file:
            file.write(response.content)
        print(f"File downloaded and saved as {file_path}")
    else:
        print("Failed to download the file")
    return file_path


def create_knowledge() -> Knowledge:
    documents = SimpleDirectoryReader(str(data_dir)).load_data()
    splitter = SentenceSplitter(chunk_size=1024)
    nodes = splitter.get_nodes_from_documents(documents)
    storage_context = StorageContext.from_defaults()
    index = VectorStoreIndex(nodes=nodes, storage_context=storage_context)
    knowledge_retriever = VectorIndexRetriever(index)
    return Knowledge(
        vector_db=LlamaIndexVectorDb(knowledge_retriever=knowledge_retriever)
    )


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
def create_agent(knowledge: Knowledge) -> Agent:
    return Agent(
        model=OpenAIChat("gpt-5.2"),
        knowledge=knowledge,
        search_knowledge=True,
        debug_mode=True,
    )


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
def run_sync() -> None:
    prepare_data()
    knowledge = create_knowledge()
    agent = create_agent(knowledge)
    agent.print_response(
        "Explain what this text means: low end eats the high end", markdown=True
    )


async def run_async() -> None:
    prepare_data()
    knowledge = create_knowledge()
    agent = create_agent(knowledge)
    await agent.aprint_response(
        "Explain what this text means: low end eats the high end",
        markdown=True,
    )


if __name__ == "__main__":
    run_sync()
    asyncio.run(run_async())
