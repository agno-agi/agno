"""
Google File Search Image Upload
================================

Demonstrates uploading images (JPEG, PNG) to Gemini File Search stores
using the multimodal embedding model (gemini-embedding-2).

This enables semantic search over image content - the model can understand
and retrieve relevant images based on natural language queries.

Requirements:
    - google-genai library must be installed and >= 1.75.0
    - GOOGLE_API_KEY environment variable must be set
    - Set IMAGE_PATH below to the path of your image file

Usage:
    .venvs/demo/bin/python cookbook/90_models/google/gemini/file_search_image_upload.py
"""

from pathlib import Path

from agno.agent import Agent
from agno.models.google import Gemini

# ---------------------------------------------------------------------------
# Configuration — set this to your image path
# ---------------------------------------------------------------------------

IMAGE_PATH = Path("path/to/your/image.jpeg")

# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------

if not IMAGE_PATH.exists():
    raise FileNotFoundError(
        f"Image not found: {IMAGE_PATH}\n"
        "Please update IMAGE_PATH at the top of this script to point to a valid JPEG or PNG file."
    )

# Determine MIME type from extension
MIME_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
mime_type = MIME_TYPES.get(IMAGE_PATH.suffix.lower())
if not mime_type:
    raise ValueError(f"Unsupported image format: {IMAGE_PATH.suffix}. Use JPEG or PNG.")

# ---------------------------------------------------------------------------
# Create model and store
# ---------------------------------------------------------------------------

model = Gemini(id="gemini-3-flash-preview")
agent = Agent(model=model, markdown=True)

# Create a multimodal store with gemini-embedding-2 for image support
print("Creating multimodal File Search store...")
store = model.create_file_search_store(
    display_name="Image Search Demo",
    embedding_model="models/gemini-embedding-2",
)
print(f"[OK] Created store: {store.name}")

# ---------------------------------------------------------------------------
# Upload image
# ---------------------------------------------------------------------------

print(f"\nUploading image: {IMAGE_PATH.name} ({mime_type})")
operation = model.upload_to_file_search_store(
    file_path=IMAGE_PATH,
    store_name=store.name,
    display_name=IMAGE_PATH.stem,
    mime_type=mime_type,
)

# Wait for upload to complete
print("Waiting for upload to complete...")
model.wait_for_operation(operation)
print("[OK] Image indexed")

# ---------------------------------------------------------------------------
# Query the image store
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print("Querying image with natural language...")
print("=" * 60)

# Configure model to use the multimodal store
model.file_search_store_names = [store.name]

run = agent.run("Write your query regarding the media?")
print(f"\nResponse:\n{run.content}")

# Display citations with media references
if run.citations and run.citations.raw:
    grounding_metadata = run.citations.raw.get("grounding_metadata", {})
    chunks = grounding_metadata.get("grounding_chunks", []) or []

    if chunks:
        print(f"\nCitations ({len(chunks)} chunks):")
        for i, chunk in enumerate(chunks[:5], 1):
            if isinstance(chunk, dict):
                retrieved_context = chunk.get("retrieved_context")
                if isinstance(retrieved_context, dict):
                    print(f"  [{i}] {retrieved_context.get('title', 'Unknown')}")
                    if retrieved_context.get("uri"):
                        print(f"      URI: {retrieved_context['uri']}")

                    # Download cited image blobs if media_id is present
                    media_id = retrieved_context.get("media_id")
                    if media_id:
                        print(f"      Media ID: {media_id}")
                        try:
                            blob_content = model.download_blob(media_id)
                            output_path = Path(
                                f"cited_image_{i}{IMAGE_PATH.suffix.lower()}"
                            )
                            output_path.write_bytes(blob_content)
                            print(
                                f"      Downloaded {len(blob_content)} bytes -> {output_path}"
                            )
                        except Exception as e:
                            print(f"      Download failed: {e}")
else:
    print("\nNo citations found")

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print("Cleaning up...")
model.delete_file_search_store(store.name, force=True)
print("[OK] Store deleted")

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
