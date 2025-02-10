"""
pip install langchain langchain-community langchain-openai langchain-chroma agno
"""

import pathlib

from agno.agent import Agent
from agno.knowledge.langchain import LangChainKnowledgeBase
from langchain.text_splitter import CharacterTextSplitter
from langchain_chroma import Chroma
from langchain_community.document_loaders import TextLoader
from langchain_openai import OpenAIEmbeddings

# Define the directory where the Chroma database is located
chroma_db_dir = pathlib.Path("./chroma_db")

# Define the path to the document to be loaded into the knowledge base
state_of_the_union = pathlib.Path("data/demo/state_of_the_union.txt")

# Load the document
raw_documents = TextLoader(str(state_of_the_union)).load()

# Split the document into chunks
text_splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=0)
documents = text_splitter.split_documents(raw_documents)

# Embed each chunk and load it into the vector store
Chroma.from_documents(
    documents, OpenAIEmbeddings(), persist_directory=str(chroma_db_dir)
)

# Get the vector database
db = Chroma(embedding_function=OpenAIEmbeddings(), persist_directory=str(chroma_db_dir))

# Create a retriever from the vector store
retriever = db.as_retriever()

# Create a knowledge base from the vector store
knowledge_base = LangChainKnowledgeBase(retriever=retriever)

# Create an agent with the knowledge base
agent = Agent(knowledge=knowledge_base)

# Use the agent to ask a question and print a response.
agent.print_response("What did the president say?", markdown=True)
