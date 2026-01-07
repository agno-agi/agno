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
    print("Citations:")
    print("=" * 50)

    # Access grounding metadata directly from citations
    grounding_metadata = run.citations.raw.get("grounding_metadata", {})
    chunks = grounding_metadata.get("grounding_chunks", []) or []

    sources = set()
    for chunk in chunks:
        if isinstance(chunk, dict):
            retrieved_context = chunk.get("retrieved_context")
            if isinstance(retrieved_context, dict):
                title = retrieved_context.get("title", "Unknown")
                sources.add(title)

    if sources:
        print(f"\nSources ({len(sources)}):")
        for i, source in enumerate(sorted(sources), 1):
            print(f"  [{i}] {source}")

        print(f"\nDetailed Citations ({len(chunks)}):")
        for i, chunk in enumerate(chunks, 1):
            if isinstance(chunk, dict):
                retrieved_context = chunk.get("retrieved_context")
                if isinstance(retrieved_context, dict):
                    print(f"\n  [{i}] {retrieved_context.get('title', 'Unknown')}")
                    if retrieved_context.get("uri"):
                        print(f"      URI: {retrieved_context['uri']}")
                    print("      Type: file_search")
                    if retrieved_context.get("text"):
                        text = retrieved_context["text"]
                        if len(text) > 200:
                            text = text[:200] + "..."
                        print(f"      Text: {text}")
    else:
        print("Citations metadata found but no File Search sources detected")
else:
    print("No citations found in response")

# Cleanup
print("\n" + "=" * 50)
print("Cleaning up...")
model.delete_file_search_store(store.name)
print("✓ Store deleted")
