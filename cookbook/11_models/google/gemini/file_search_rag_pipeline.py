import asyncio
from pathlib import Path

from agno.agent import Agent
from agno.models.google import Gemini

# Configuration
DOCUMENTS_DIR = (
    Path(__file__).parent / "documents"
)  # Use documents directory in same folder
STORE_NAME = "RAG Pipeline Demo"


async def create_and_populate_store(model: Gemini, documents_dir: Path):
    """Create a File Search store and upload all documents from a directory."""
    print(f"Creating File Search store: {STORE_NAME}")
    store = await model.async_create_file_search_store(display_name=STORE_NAME)
    print(f"✓ Store created: {store.name}")

    # Find all supported documents
    supported_extensions = [".txt", ".pdf", ".md", ".json", ".py", ".js", ".ts"]
    files = [
        f
        for f in documents_dir.glob("**/*")
        if f.suffix.lower() in supported_extensions
    ]

    print(f"\nFound {len(files)} documents to upload")

    # Upload files with progress tracking
    upload_operations = []
    for i, file_path in enumerate(files, 1):
        print(f"  [{i}/{len(files)}] Uploading {file_path.name}...")

        # Determine chunking config based on file type
        chunking_config = None
        if file_path.suffix in [".py", ".js", ".ts"]:
            # Code files - smaller chunks for precise retrieval
            chunking_config = {
                "white_space_config": {
                    "max_tokens_per_chunk": 150,
                    "max_overlap_tokens": 30,
                }
            }
        else:
            # Documentation files - larger chunks for context
            chunking_config = {
                "white_space_config": {
                    "max_tokens_per_chunk": 300,
                    "max_overlap_tokens": 50,
                }
            }

        # Metadata based on file properties
        metadata = [
            {"key": "filename", "string_value": file_path.name},
            {"key": "extension", "string_value": file_path.suffix},
            {"key": "size_kb", "numeric_value": file_path.stat().st_size // 1024},
        ]

        operation = await model.async_upload_to_file_search_store(
            file_path=file_path,
            store_name=store.name,
            display_name=file_path.stem,
            chunking_config=chunking_config,
            custom_metadata=metadata,
        )
        upload_operations.append((file_path.name, operation))

    # Wait for all uploads to complete
    print("\nWaiting for all uploads to complete...")
    for filename, operation in upload_operations:
        try:
            await model.async_wait_for_operation(operation, max_wait=300)
            print(f"  ✓ {filename} indexed")
        except TimeoutError:
            print(f"  ✗ {filename} timed out")
        except Exception as e:
            print(f"  ✗ {filename} failed: {e}")

    return store


async def query_with_citations(model: Gemini, query: str, store_name: str):
    """Query the File Search store and display results with citations."""
    print(f"\nQuery: {query}")
    print("=" * 80)

    # Configure model to use File Search
    model.file_search_store_names = [store_name]

    # Create agent and get response
    agent = Agent(model=model, markdown=True)
    run = agent.run(query)
    print(f"\nAnswer:\n{run.content}")

    # Extract and display citations directly from run.citations
    sources = []
    chunks = []

    if run.citations and run.citations.raw:
        grounding_metadata = run.citations.raw.get("grounding_metadata", {})
        grounding_chunks = grounding_metadata.get("grounding_chunks", []) or []

        sources_set = set()
        for chunk in grounding_chunks:
            if isinstance(chunk, dict):
                retrieved_context = chunk.get("retrieved_context")
                if isinstance(retrieved_context, dict):
                    title = retrieved_context.get("title", "Unknown")
                    sources_set.add(title)
                    chunks.append(
                        {
                            "title": title,
                            "uri": retrieved_context.get("uri", ""),
                            "text": retrieved_context.get("text", ""),
                            "type": "file_search",
                        }
                    )

        sources = sorted(list(sources_set))

    if sources:
        print("\n" + "─" * 80)
        print(f"Sources ({len(sources)} documents):")
        for i, source in enumerate(sources, 1):
            print(f"  [{i}] {source}")

        if chunks:
            print(f"\nCitations ({len(chunks)} chunks):")
            for i, chunk in enumerate(chunks[:3], 1):  # Show first 3
                print(f"\n  [{i}] {chunk['title']}")
                if chunk.get("text"):
                    text = chunk["text"]
                    if len(text) > 150:
                        text = text[:150] + "..."
                    print(f'      "{text}"')
    else:
        print("\nNo citations found")

    return run, {"sources": sources, "grounding_chunks": chunks}


async def main():
    """Main RAG pipeline execution."""
    print("=" * 80)
    print("RAG Pipeline with Gemini File Search")
    print("=" * 80)

    # Check if documents directory exists
    if not DOCUMENTS_DIR.exists():
        print(f"\n✗ Error: Documents directory not found: {DOCUMENTS_DIR}")
        print("Please create the directory and add some documents to index.")
        return

    # Initialize model
    model = Gemini(id="gemini-2.5-flash")

    # Step 1: Create and populate store
    print("\n" + "=" * 80)
    print("Step 1: Creating and populating File Search store")
    print("=" * 80)

    try:
        store = await create_and_populate_store(model, DOCUMENTS_DIR)
    except Exception as e:
        print(f"\n✗ Error creating store: {e}")
        return

    # Step 2: List and verify documents
    print("\n" + "=" * 80)
    print("Step 2: Verifying uploaded documents")
    print("=" * 80)

    documents = await model.async_list_documents(store.name)
    print(f"\n✓ Total documents in store: {len(documents)}")
    print("\nDocuments:")
    for doc in documents[:10]:  # Show first 10
        print(f"  - {doc.display_name}")
    if len(documents) > 10:
        print(f"  ... and {len(documents) - 10} more")

    # Step 3: Interactive querying
    print("\n" + "=" * 80)
    print("Step 3: Querying the knowledge base")
    print("=" * 80)

    queries = [
        "What are the main topics covered in the documentation?",
        "Can you summarize the key technical concepts?",
        "What code examples are available?",
    ]

    all_citations = []
    for query in queries:
        response, citations = await query_with_citations(model, query, store.name)
        all_citations.append(citations)

    # Step 4: Citation analysis
    print("\n" + "=" * 80)
    print("Step 4: Citation Analysis")
    print("=" * 80)

    all_sources = set()
    for citations in all_citations:
        all_sources.update(citations["sources"])

    print(f"\n✓ Total unique sources referenced: {len(all_sources)}")
    print(f"✓ Document coverage: {len(all_sources)}/{len(documents)} documents")

    # Step 5: Cleanup
    print("\n" + "=" * 80)
    print("Step 5: Cleanup")
    print("=" * 80)

    try:
        await model.async_delete_file_search_store(store.name, force=True)
        print(f"✓ Store deleted: {store.name}")
    except Exception as e:
        print(f"✗ Error deleting store: {e}")

    print("\n" + "=" * 80)
    print("✓ RAG Pipeline completed successfully!")
    print("=" * 80)


# Run the async main function
if __name__ == "__main__":
    asyncio.run(main())
