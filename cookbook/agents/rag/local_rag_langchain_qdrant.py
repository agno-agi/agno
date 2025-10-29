"""
Prerequisites:
 - pip install langchain-qdrant langchain-text-splitters langchain-community fastembed
"""

from agno.agent import Agent
from agno.models.ollama import Ollama
from agno.vectordb.langchaindb import LangChainVectorDb
from langchain_community.document_loaders import WebBaseLoader
from langchain_community.embeddings.fastembed import FastEmbedEmbeddings
from langchain_qdrant import QdrantVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.http.models import Distance, VectorParams

urls = [
    "https://blog.google/technology/developers/gemma-3/",
]

loader = WebBaseLoader(urls)
data = loader.load()
text_splitter = RecursiveCharacterTextSplitter(chunk_size=1024, chunk_overlap=50)
chunks = text_splitter.split_documents(data)
embeddings = FastEmbedEmbeddings(model_name="thenlper/gte-large")

client = QdrantClient(path="/tmp/app")
collection_name = "agent-rag"

try:
    collection_info = client.get_collection(collection_name=collection_name)
except (UnexpectedResponse, ValueError):
    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
    )

vector_store = QdrantVectorStore(
    client=client,
    collection_name=collection_name,
    embedding=embeddings,
)

vector_store.add_documents(documents=chunks)
retriever = vector_store.as_retriever()

knowledge_base = LangChainVectorDb(knowledge_retriever=retriever)

agent = Agent(
    model=Ollama(id="qwen2.5:latest"),
    knowledge=knowledge_base,
    description="Answer to the user question from the knowledge base",
    markdown=True,
    search_knowledge=True,
)

user_query = "What are the new capabilities developers can use with Gemma 3"
agent.print_response(user_query, stream=True)
