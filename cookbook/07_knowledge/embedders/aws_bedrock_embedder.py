"""
AWS Bedrock Embedder Example - Cohere Embed v3

This example demonstrates how to use the AWS Bedrock Embedder with Cohere Embed v3 models.

Requirements:
- AWS credentials (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
- AWS region configured (AWS_REGION)
- boto3 installed: pip install boto3
"""

from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.embedder.aws_bedrock import AwsBedrockEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.pdf_reader import PDFReader
from agno.vectordb.pgvector import PgVector

# Basic text embedding with v3 model (default)
embedder = AwsBedrockEmbedder()
embeddings = embedder.get_embedding("The quick brown fox jumps over the lazy dog.")

# Print the embeddings and their dimensions
print(f"Embeddings (first 5): {embeddings[:5]}")
print(f"Dimensions: {len(embeddings)}")

# Example usage with Knowledge and PgVector
knowledge = Knowledge(
    vector_db=PgVector(
        table_name="recipes",
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        embedder=AwsBedrockEmbedder(
            input_type="search_document",  # Use search_document for indexing
        ),
    ),
)

# Insert documents (embedder will automatically use search_document type)
# Note: Cohere Embed v3 models have a 2048 token limit per text input,
# so we use smaller chunks to stay within the limit
knowledge.insert(
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    reader=PDFReader(chunking_strategy=FixedSizeChunking(chunk_size=1500)),
)
