"""
AWS Bedrock Embedder Example - Cohere Embed v4

This example demonstrates the new Cohere Embed v4 features on AWS Bedrock:
- Configurable output dimensions (256, 512, 1024, 1536)
- Multimodal embeddings (text + images)

Requirements:
- AWS credentials (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
- AWS region configured (AWS_REGION)
- boto3 installed: pip install boto3
"""

from agno.knowledge.embedder.aws_bedrock import AwsBedrockEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

# Create v4 embedder with custom dimensions
embedder_v4 = AwsBedrockEmbedder(
    id="cohere.embed-v4:0",
    output_dimension=1024,  # Options: 256, 512, 1024, 1536
    input_type="search_query",
)

# Basic text embedding
text = "What is machine learning?"
embeddings = embedder_v4.get_embedding(text)

print(f"Model: {embedder_v4.id}")
print(f"Embeddings (first 5): {embeddings[:5]}")
print(f"Dimensions: {len(embeddings)}")

# Example with different dimension configurations
print("\n--- Testing different dimensions ---")
for dim in [256, 512, 1024, 1536]:
    emb = AwsBedrockEmbedder(
        id="cohere.embed-v4:0",
        output_dimension=dim,
    )
    result = emb.get_embedding("Test text")
    print(f"Dimension {dim}: Got {len(result)} dimensional vector")

# Example usage with Knowledge for RAG
# Use higher dimensions for better accuracy, lower for faster search
knowledge = Knowledge(
    vector_db=PgVector(
        table_name="ml_knowledge",
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        embedder=AwsBedrockEmbedder(
            id="cohere.embed-v4:0",
            output_dimension=1024,
            input_type="search_document",
        ),
    ),
)

# Note: Multimodal embeddings example (requires actual image data)
# Image embedding (v4 only):
#   image_uri = "data:image/png;base64,<base64-encoded-image>"
#   image_embedding = embedder_v4.get_image_embedding(image_uri)
#
# Multimodal embedding (v4 only):
#   content = [
#       {"type": "text", "text": "Product description"},
#       {"type": "image_url", "image_url": "data:image/png;base64,..."}
#   ]
#   multimodal_embedding = embedder_v4.get_multimodal_embedding(content)
