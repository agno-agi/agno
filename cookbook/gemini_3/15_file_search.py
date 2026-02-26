"""
15. File Search (Server-side RAG)
=================================
Gemini's File Search lets you upload documents to a managed store
and query them with automatic chunking, embedding, and retrieval.
No vector database setup needed -- it's all server-side.

Run:
    python cookbook/gemini_3/15_file_search.py

Note: This creates a temporary store, queries it, and cleans up.
"""

from pathlib import Path
from textwrap import dedent

from agno.agent import Agent
from agno.models.google import Gemini

# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------
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
    # Step 1: Create a File Search store
    print("Creating File Search store...")
    store = model.create_file_search_store(display_name="Guidelines Store")
    print(f"Created store: {store.name}")

    # Step 2: Upload the document
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
    model.delete_file_search_store(store.name)
    print("Done.")
