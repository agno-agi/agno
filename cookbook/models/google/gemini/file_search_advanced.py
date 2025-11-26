from pathlib import Path

from agno.agent import Agent
from agno.models.google import Gemini

# Create Gemini model
model = Gemini(id="gemini-2.5-flash")

# Create agent
agent = Agent(model=model, markdown=True)

print("=" * 60)
print("Setting up multiple File Search stores...")
print("=" * 60)

# Create two different stores for different types of content
technical_store = model.create_file_search_store(display_name="Technical Documentation")
marketing_store = model.create_file_search_store(display_name="Marketing Content")

print(f"✓ Created technical store: {technical_store.name}")
print(f"✓ Created marketing store: {marketing_store.name}")

# Upload files with custom chunking and metadata
print("\n" + "=" * 60)
print("Uploading files with custom configuration...")
print("=" * 60)

# Upload technical document with custom chunking
print("\n1. Uploading technical document...")
tech_operation = model.upload_to_file_search_store(
    file_path=Path(__file__).parent / "documents" / "technical_manual.txt",
    store_name=technical_store.name,
    display_name="Technical Manual v2.0",
    chunking_config={
        "white_space_config": {
            "max_tokens_per_chunk": 300,
            "max_overlap_tokens": 50,
        }
    },
    custom_metadata=[
        {"key": "type", "string_value": "technical"},
        {"key": "version", "numeric_value": 2},
        {"key": "department", "string_value": "engineering"},
    ],
)

# Upload marketing document
print("2. Uploading marketing document...")
marketing_operation = model.upload_to_file_search_store(
    file_path=Path(__file__).parent / "documents" / "product_brochure.txt",
    store_name=marketing_store.name,
    display_name="Product Brochure Q1 2024",
    chunking_config={
        "white_space_config": {
            "max_tokens_per_chunk": 200,
            "max_overlap_tokens": 20,
        }
    },
    custom_metadata=[
        {"key": "type", "string_value": "marketing"},
        {"key": "quarter", "string_value": "Q1"},
        {"key": "year", "numeric_value": 2024},
    ],
)

# Wait for both uploads
print("\nWaiting for uploads to complete...")
model.wait_for_operation(tech_operation)
print("✓ Technical document uploaded")
model.wait_for_operation(marketing_operation)
print("✓ Marketing document uploaded")

# List documents in each store
print("\n" + "=" * 60)
print("Document Management")
print("=" * 60)

print("\nTechnical Store Documents:")
tech_docs = model.list_documents(technical_store.name)
for doc in tech_docs:
    print(f"  - {doc.display_name} ({doc.name})")

print("\nMarketing Store Documents:")
marketing_docs = model.list_documents(marketing_store.name)
for doc in marketing_docs:
    print(f"  - {doc.display_name} ({doc.name})")

# Query with metadata filtering - Technical docs only
print("\n" + "=" * 60)
print("Query 1: Technical documentation with metadata filter")
print("=" * 60)

model.file_search_store_names = [technical_store.name]
model.file_search_metadata_filter = 'type="technical" AND version=2'

run1 = agent.run(
    "What are the technical specifications mentioned in the documentation?"
)
print(f"\nResponse:\n{run1.content}")

if run1.citations and run1.citations.raw:
    print("\nCitations:")
    print("=" * 50)
    grounding_metadata = run1.citations.raw.get("grounding_metadata", {})
    sources = set()
    for chunk in grounding_metadata.get("grounding_chunks", []) or []:
        if isinstance(chunk, dict) and chunk.get("retrieved_context"):
            rc = chunk["retrieved_context"]
            sources.add(rc.get("title", "Unknown"))
    if sources:
        print(f"\nSources ({len(sources)}):")
        for i, source in enumerate(sorted(sources), 1):
            print(f"  [{i}] {source}")

# Query across multiple stores
print("\n" + "=" * 60)
print("Query 2: Search across both stores")
print("=" * 60)

model.file_search_store_names = [technical_store.name, marketing_store.name]
model.file_search_metadata_filter = None  # Remove filter

run2 = agent.run("What are the key product features and how do they work?")
print(f"\nResponse:\n{run2.content}")

if run2.citations and run2.citations.raw:
    print("\nCitations:")
    print("=" * 50)
    grounding_metadata = run2.citations.raw.get("grounding_metadata", {})
    chunks = grounding_metadata.get("grounding_chunks", []) or []

    sources = set()
    for chunk in chunks:
        if isinstance(chunk, dict) and chunk.get("retrieved_context"):
            rc = chunk["retrieved_context"]
            sources.add(rc.get("title", "Unknown"))

    if sources:
        print(f"\nSources ({len(sources)}):")
        for i, source in enumerate(sorted(sources), 1):
            print(f"  [{i}] {source}")

        print(f"\nDetailed Citations ({len(chunks)}):")
        for i, chunk in enumerate(chunks, 1):
            if isinstance(chunk, dict) and chunk.get("retrieved_context"):
                rc = chunk["retrieved_context"]
                print(f"\n  [{i}] {rc.get('title', 'Unknown')}")
                if rc.get("uri"):
                    print(f"      URI: {rc['uri']}")
                print("      Type: file_search")
                if rc.get("text"):
                    text = rc["text"]
                    if len(text) > 200:
                        text = text[:200] + "..."
                    print(f"      Text: {text}")

# Update document metadata (API not yet available)
print("\n" + "=" * 60)
print("Document metadata management...")
print("=" * 60)

if tech_docs:
    print(f"✓ Document retrieved: {tech_docs[0].display_name}")
    print(f"  Document ID: {tech_docs[0].name}")
    # Note: Document update API is not yet available in the current SDK version
    print("  (Metadata update API coming soon)")

# Cleanup
print("\n" + "=" * 60)
print("Cleaning up...")
print("=" * 60)

model.delete_file_search_store(technical_store.name)
print(f"✓ Deleted {technical_store.name}")

model.delete_file_search_store(marketing_store.name)
print(f"✓ Deleted {marketing_store.name}")

print("\n✓ Example completed successfully!")
