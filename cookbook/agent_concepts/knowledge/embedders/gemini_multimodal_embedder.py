from agno.embedder.google import GeminiEmbedder
from agno.media import Image, Audio

# 1. Text Embedding
text_embeddings = GeminiEmbedder().get_embedding(
    "The quick brown fox jumps over the lazy dog."
)
print(f"Text Embeddings: {text_embeddings[:5]}...")

# 2. Image Embedding
# Note: You would normally provide a real image file or bytes
image_embeddings = GeminiEmbedder().get_multimodal_embedding(
    Image(url="https://upload.wikimedia.org/wikipedia/commons/thumb/4/47/PNG_transparency_demonstration_1.png/280px-PNG_transparency_demonstration_1.png")
)
print(f"Image Embeddings: {image_embeddings[:5]}...")

# 3. Audio Embedding
# audio_embeddings = GeminiEmbedder().get_multimodal_embedding(
#     Audio(filepath="path/to/audio.mp3")
# )

# 4. Batch Text Embeddings
batch_embeddings = GeminiEmbedder().get_embeddings(
    ["First sentence", "Second sentence", "Third sentence"]
)
print(f"Batch Embeddings Count: {len(batch_embeddings)}")
