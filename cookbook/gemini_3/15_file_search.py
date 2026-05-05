"""
File Search - Server-Side RAG with Citations
==============================================
Upload documents to a Google-managed store and query them with automatic RAG.

Key concepts:
- create_file_search_store: Creates a managed document store on Google's servers
- upload_to_file_search_store: Uploads documents for automatic chunking and indexing
- file_search_store_names: Links the store to your Gemini model
- Citations: Responses include source references you can verify
- Managed RAG: No ChromaDB, no embeddings config. Google handles it all

Example prompts to try:
- "What are the main safety guidelines?"
- "What should I do if I see a hazard?"
"""

from pathlib import Path
from textwrap import dedent

from agno.agent import Agent
from agno.models.google import Gemini

WORKSPACE = Path(__file__).parent.joinpath("workspace")
WORKSPACE.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Create a sample document
# ---------------------------------------------------------------------------
SAMPLE_DOC = WORKSPACE / "company_guidelines.txt"
SAMPLE_DOC.write_text(
    dedent("""\
    Company Safety Guidelines

    1. All employees must wear safety equipment in the warehouse.
    2. Fire exits must remain clear at all times.
    3. Report any safety hazards to your supervisor immediately.
    4. First aid kits are located on every floor near the elevators.
    5. Emergency drills are conducted quarterly.
    6. Remote workers should ensure their home office meets ergonomic standards.
    7. All incidents, no matter how minor, must be documented within 24 hours.
    8. Visitors must be accompanied by an employee at all times.
    """)
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
model = Gemini(id="gemini-3.1-pro-preview")

file_search_agent = Agent(
    name="File Search Agent",
    model=model,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Step 1: Create a File Search store (managed by Google)
    print("Creating File Search store...")
    store = model.create_file_search_store(display_name="Guidelines Store")
    print(f"Created store: {store.name}")

    # Step 2: Upload the document (auto-chunked and indexed)
    print("\nUploading document...")
    operation = model.upload_to_file_search_store(
        file_path=SAMPLE_DOC,
        store_name=store.name,
        display_name="Company Safety Guidelines",
    )

    print("Waiting for upload to complete...")
    model.wait_for_operation(operation)
    print("Upload complete.")

    # Step 3: Configure model to use the store
    model.file_search_store_names = [store.name]

    # Step 4: Query the documents
    print("\nQuerying documents...\n")
    run = file_search_agent.run(
        "What are the main safety guidelines? What should I do if I see a hazard?"
    )
    print(run.content)

    # Step 5: Show citations
    if run.citations and run.citations.raw:
        grounding_metadata = run.citations.raw.get("grounding_metadata", {})
        chunks = grounding_metadata.get("grounding_chunks", []) or []
        if chunks:
            print(f"\nCitations ({len(chunks)} sources found)")

    # Cleanup
    print("\nCleaning up store...")
    model.delete_file_search_store(store.name, force=True)
    print("Done.")

# ---------------------------------------------------------------------------
# More Examples
# ---------------------------------------------------------------------------
"""
File Search vs local Knowledge (step 17):

File Search (this example):
- Fully managed by Google, no local vector DB
- Automatic chunking and embedding
- Built-in citation support
- Best for: quick prototyping, small document sets, when you don't want infra

Local Knowledge (step 17):
- Uses ChromaDb (or PgVector) locally
- You control chunking, embedding model, and search strategy
- Hybrid search (semantic + keyword)
- Best for: production apps, large document sets, custom search logic

Upload multiple files:
    for doc in ["report.pdf", "faq.txt", "manual.pdf"]:
        model.upload_to_file_search_store(
            file_path=doc, store_name=store.name, display_name=doc
        )
"""
