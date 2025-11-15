from pathlib import Path

from agno.agent import Agent
from agno.models.google import Gemini

# Create Gemini model
model = Gemini(id="gemini-2.5-flash")

# Create agent with the model
agent = Agent(model=model, markdown=True)

print("Creating File Search store...")
store = model.create_file_search_store(display_name="Basic Demo Store")
print(f"✓ Created store: {store.name}")

print("\nUploading file to store...")
# Upload a file directly to the File Search store
operation = model.upload_to_file_search_store(
    file_path=Path(__file__).parent / "documents" / "sample.txt",
    store_name=store.name,
    display_name="Sample Document",
)

# Wait for upload to complete
print("Waiting for upload to complete...")
completed_op = model.wait_for_operation(operation)
print("✓ Upload completed")

# Configure model to use File Search
model.file_search_store_names = [store.name]

# Query the documents
print("\nQuerying documents...")
run = agent.run(
    "Can you tell me about the content in the uploaded document? Specifically, what are the main safety guidelines mentioned?"
)
print(f"\nResponse:\n{run.content}")

# Extract and display citations
print("\n" + "=" * 50)
if run.citations and run.citations.raw:
    # Use our custom citation formatter
    citations_dict = {
        "sources": [],
        "grounding_chunks": [],
        "raw_metadata": run.citations.raw.get("grounding_metadata", {}),
    }

    # Extract from grounding metadata
    grounding_metadata = run.citations.raw.get("grounding_metadata", {})
    chunks = grounding_metadata.get("grounding_chunks", []) or []
    for chunk in chunks:
        if isinstance(chunk, dict):
            retrieved_context = chunk.get("retrieved_context")
            if isinstance(retrieved_context, dict):
                title = retrieved_context.get("title", "Unknown")
                citations_dict["sources"].append(title)
                citations_dict["grounding_chunks"].append(
                    {
                        "title": title,
                        "uri": retrieved_context.get("uri", ""),
                        "text": retrieved_context.get("text", ""),
                        "type": "file_search",
                    }
                )

    if citations_dict["sources"]:
        formatted_citations = model.format_citations(
            citations_dict, include_text=True
        )
        print(formatted_citations)
    else:
        print("Citations metadata found but no File Search sources detected")
else:
    print("No citations found in response")

# Cleanup
print("\n" + "=" * 50)
print("Cleaning up...")
model.delete_file_search_store(store.name)
print("✓ Store deleted")
