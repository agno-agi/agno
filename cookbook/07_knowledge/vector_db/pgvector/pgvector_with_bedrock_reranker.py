"""
AWS Bedrock Reranker Example with PgVector

This example demonstrates how to use AWS Bedrock Reranker with PgVector for RAG.
Supports both Cohere Rerank 3.5 and Amazon Rerank 1.0 models.

Requirements:
- AWS credentials (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
- AWS region configured (AWS_REGION)
- boto3 installed: pip install boto3
- PostgreSQL with pgvector running
"""

from agno.agent import Agent
from agno.knowledge.embedder.aws_bedrock import AwsBedrockEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reranker.aws_bedrock import (
    AmazonReranker,
    AwsBedrockReranker,
    CohereBedrockReranker,
)
from agno.models.aws import AwsBedrock```
from agno.vectordb.pgvector import PgVector

# Option 1: Using AwsBedrockReranker with Cohere Rerank 3.5
knowledge_cohere = Knowledge(
    vector_db=PgVector(
        table_name="bedrock_rag_demo",
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        embedder=AwsBedrockEmbedder(
            id="cohere.embed-multilingual-v3",
            input_type="search_document",
        ),
        reranker=AwsBedrockReranker(
            model="cohere.rerank-v3-5:0",
            top_n=5,  # Return top 5 most relevant results
        ),
    ),
)

# Option 2: Using convenience class CohereBedrockReranker
knowledge_convenience = Knowledge(
    vector_db=PgVector(
        table_name="bedrock_rag_demo_v2",
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        embedder=AwsBedrockEmbedder(
            id="cohere.embed-v4:0",
            output_dimension=1024,
            input_type="search_document",
        ),
        reranker=CohereBedrockReranker(top_n=5),
    ),
)

# Option 3: Using Amazon Rerank 1.0
# Note: Amazon Rerank 1.0 is NOT available in us-east-1
knowledge_amazon = Knowledge(
    vector_db=PgVector(
        table_name="bedrock_rag_amazon",
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        embedder=AwsBedrockEmbedder(
            id="cohere.embed-multilingual-v3",
            input_type="search_document",
        ),
        reranker=AmazonReranker(
            top_n=5,
            aws_region="us-west-2",  # Amazon Rerank not available in us-east-1
        ),
    ),
)

# Example: Insert documents
knowledge_cohere.insert(
    name="Agno Docs",
    url="https://docs.agno.com/introduction.md",
)

# Create an agent with Bedrock model and knowledge
agent = Agent(
    model=AWSBedrock(id="anthropic.claude-sonnet-4-20250514-v1:0"),
    knowledge=knowledge_cohere,
    markdown=True,
)

if __name__ == "__main__":
    # Load the knowledge base (comment after first run)
    # agent.knowledge.load(recreate=True)
    agent.print_response("What are the key features?")
