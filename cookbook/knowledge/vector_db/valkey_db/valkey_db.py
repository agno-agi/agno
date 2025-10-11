"""
Valkey Search Vector Database Example

This example demonstrates how to use Valkey Search as a vector database with Agno.
Valkey Search is a Redis-compatible search engine that supports vector similarity search.

Prerequisites:
1. Start Valkey with Docker Compose:
   cd cookbook/knowledge/vector_db/valkey_db/
   docker-compose up -d

2. Set your OpenAI API key:
   export OPENAI_API_KEY="your-api-key-here"
"""

import asyncio
from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.agent import Agent
from agno.vectordb.valkey import ValkeySearch
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.models.openai import OpenAIChat
from agno.db.json import JsonDb


def valkey_db():
    """Basic example of using Valkey Search with Agno."""
    print("Valkey Search Vector Database Example")
    print("=" * 50)
    
    # Initialize Valkey Search with explicit smaller embedder configuration
    # Use text-embedding-ada-002 (1536 dimensions) for reliability
    embedder = OpenAIEmbedder(
        id="text-embedding-ada-002",
        dimensions=1536
    )
    valkey_search = ValkeySearch(
        collection="test_collection",
        embedder=embedder,
        host="localhost",
        port=6379,
    )
    
    # Create the index
    print("Creating index...")
    valkey_search.create()
    
    # Create sample documents
    documents = [
        Document(
            id="doc1",
            content="Python is a high-level programming language.",
            meta_data={"category": "programming", "language": "python"}
        ),
        Document(
            id="doc2", 
            content="Machine learning is a subset of artificial intelligence.",
            meta_data={"category": "AI", "topic": "machine learning"}
        ),
        Document(
            id="doc3",
            content="Vector databases store and search high-dimensional vectors.",
            meta_data={"category": "database", "type": "vector"}
        ),
    ]
    
    # Insert documents
    print("Inserting documents...")
    valkey_search.insert("content_hash_123", documents)
    
    # Search for similar documents
    print("Searching for 'programming languages'...")
    results = valkey_search.search("programming languages", limit=3)
    
    print(f"Found {len(results)} results:")
    for i, doc in enumerate(results, 1):
        print(f"{i}. {doc.content[:50]}... (score: {doc.reranking_score or 0.0:.4f})")
        print(f"   Metadata: {doc.meta_data}")
        print()
    
    # Clean up
    print("Cleaning up...")
    valkey_search.drop()


async def async_valkey_db():
    """Async example of using Valkey Search with Agno."""
    print("Async Valkey Search Example")
    print("=" * 50)
    
    # Initialize Valkey Search with explicit embedder configuration
    embedder = OpenAIEmbedder(
        id="text-embedding-ada-002",
        dimensions=1536
    )
    valkey_search = ValkeySearch(
        collection="async_test_collection",
        embedder=embedder,
        host="localhost",
        port=6379,
    )
    
    # Create the index
    print("Creating index...")
    await valkey_search.async_create()
    
    # Create sample documents
    documents = [
        Document(
            id="async_doc1",
            content="Asynchronous programming allows concurrent execution.",
            meta_data={"category": "programming", "type": "async"}
        ),
        Document(
            id="async_doc2",
            content="Event loops manage asynchronous operations efficiently.",
            meta_data={"category": "programming", "type": "async"}
        ),
    ]
    
    # Insert documents
    print("Inserting documents...")
    await valkey_search.async_insert("async_content_hash_456", documents)
    
    # Search for similar documents
    print("Searching for 'async programming'...")
    results = await valkey_search.async_search("async programming", limit=2)
    
    print(f"Found {len(results)} results:")
    for i, doc in enumerate(results, 1):
        print(f"{i}. {doc.content[:50]}... (score: {doc.reranking_score or 0.0:.4f})")
        print(f"   Metadata: {doc.meta_data}")
        print()
    
    # Clean up
    print("Cleaning up...")
    await valkey_search.async_drop()


def valkey_db_with_knowledge():
    """Example using Valkey Search with Agno Knowledge system."""
    print("Valkey Search with Knowledge System")
    print("=" * 50)
    
    # Initialize Valkey Search with explicit embedder configuration
    embedder = OpenAIEmbedder(
        id="text-embedding-ada-002",
        dimensions=1536
    )
    valkey_search = ValkeySearch(
        collection="knowledge_collection",
        embedder=embedder,
        host="localhost",
        port=6379,
    )
    
    # Create Contents DB for metadata storage (optional but recommended)
    contents_db = JsonDb(
        db_path="./valkey_knowledge_data",
        knowledge_table="valkey_knowledge_contents"
    )
    
    # Create Knowledge system
    knowledge = Knowledge(
        name="Valkey Knowledge Base",
        vector_db=valkey_search,
        contents_db=contents_db,
    )
    
    # Add documents to knowledge base using the proper API
    print("Adding documents to knowledge base...")
    
    # Add text content using the correct Knowledge API
    knowledge.add_content(
        name="AI Technology",
        text_content="Artificial intelligence is transforming industries.",
        metadata={"category": "technology", "topic": "AI"}
    )
    knowledge.add_content(
        name="Blockchain Technology", 
        text_content="Blockchain technology enables decentralized systems.",
        metadata={"category": "technology", "topic": "blockchain"}
    )
    knowledge.add_content(
        name="Quantum Computing",
        text_content="Quantum computing promises exponential speedups.",
        metadata={"category": "science", "topic": "quantum"}
    )
    
    # Create agent with knowledge
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        knowledge=knowledge,
        search_knowledge=True,
        instructions="You are a helpful assistant with access to a knowledge base."
    )
    
    # Query the agent
    print("Querying agent with knowledge...")
    response = agent.run("What technologies are transforming industries?")
    print(f"Agent response: {response.content}")
    
    # Clean up
    print("Cleaning up...")
    valkey_search.drop()


def valkey_db_advanced():
    """Advanced example with filters and metadata search."""
    print("Advanced Valkey Search Example")
    print("=" * 50)
    
    # Initialize Valkey Search with explicit embedder configuration
    valkey_search = ValkeySearch(
        collection="advanced_collection",
        embedder=OpenAIEmbedder(
            id="text-embedding-ada-002",
            dimensions=1536
        ),
        host="localhost",
        port=6379,
    )
    
    # Create the index
    print("Creating index...")
    valkey_search.create()
    
    # Create sample documents with different categories
    documents = [
        Document(
            id="tech1",
            content="Artificial intelligence is transforming industries.",
            meta_data={"category": "technology", "topic": "AI", "year": 2024}
        ),
        Document(
            id="tech2",
            content="Blockchain technology enables decentralized systems.",
            meta_data={"category": "technology", "topic": "blockchain", "year": 2024}
        ),
        Document(
            id="science1",
            content="Quantum computing promises exponential speedups.",
            meta_data={"category": "science", "topic": "quantum", "year": 2024}
        ),
        Document(
            id="science2",
            content="Climate change research requires urgent action.",
            meta_data={"category": "science", "topic": "climate", "year": 2024}
        ),
    ]
    
    # Insert documents
    print("Inserting documents...")
    valkey_search.insert("advanced_content_hash_789", documents)
    
    # Search without filters first (Valkey Search filter implementation needs work)
    print("Searching for 'technology innovation'...")
    results = valkey_search.search("technology innovation", limit=3)
    
    print(f"Found {len(results)} results:")
    for i, doc in enumerate(results, 1):
        print(f"{i}. {doc.content[:50]}... (score: {doc.reranking_score or 0.0:.4f})")
        print(f"   Metadata: {doc.meta_data}")
        print()
    
    # Search for science-related content
    print("Searching for 'quantum research'...")
    results = valkey_search.search("quantum research", limit=3)
    
    print(f"Found {len(results)} results:")
    for i, doc in enumerate(results, 1):
        print(f"{i}. {doc.content[:50]}... (score: {doc.reranking_score or 0.0:.4f})")
        print(f"   Metadata: {doc.meta_data}")
        print()
    
    # Clean up
    print("Cleaning up...")
    valkey_search.drop()


if __name__ == "__main__":
    print("Valkey Search Vector Database Examples")
    print("=" * 60)
    print()
    print("Make sure Valkey is running with the search module loaded!")
    print("Start Valkey with: docker-compose up -d")
    print("Check health with: docker-compose ps")
    print()
    
    try:
        # Run basic example
        valkey_db()
        print()
        
        # Run async example
        asyncio.run(async_valkey_db())
        print()
        
        # Run knowledge system example
        valkey_db_with_knowledge()
        print()
        
        # Run advanced example
        valkey_db_advanced()
        
    except Exception as e:
        print(f"Error: {e}")
        print()
        print("Make sure:")
        print("1. Valkey is running with the search module")
        print("2. OpenAI API key is set (export OPENAI_API_KEY='your-key')")