from agno.document.reader.pdf_reader import PDFUrlReader
from agno.embedder.aws_bedrock import AwsBedrockEmbedder
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.vectordb.pgvector import PgVector

embeddings = AwsBedrockEmbedder().get_embedding(
    "The quick brown fox jumps over the lazy dog."
)
# Print the embeddings and their dimensions
print(f"Embeddings: {embeddings[:5]}")
print(f"Dimensions: {len(embeddings)}")

# Example usage:
knowledge_base = PDFUrlKnowledgeBase(
    urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
    reader=PDFUrlReader(
        chunk_size=2048
    ),  # Required because cohere has a fixed size of 2048
    vector_db=PgVector(
        table_name="recipes",
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        embedder=AwsBedrockEmbedder(),
    ),
)
knowledge_base.load(recreate=False)
