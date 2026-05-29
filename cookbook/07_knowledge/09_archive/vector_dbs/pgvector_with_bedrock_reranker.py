"""
AWS Bedrock Reranker Example with PgVector
==========================================

Demonstrates AWS Bedrock rerankers with PgVector for retrieval augmented generation.

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
from agno.models.aws.bedrock import AwsBedrock
from agno.vectordb.pgvector import PgVector

# ---------------------------------------------------------------------------
# Create Knowledge Base
# ---------------------------------------------------------------------------
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
            top_n=5,
        ),
    ),
)

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
            aws_region="us-west-2",
        ),
    ),
)


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=AwsBedrock(id="anthropic.claude-sonnet-4-20250514-v1:0"),
    knowledge=knowledge_cohere,
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
def main() -> None:
    knowledge_cohere.insert(
        name="Agno Docs", url="https://docs.agno.com/introduction.md"
    )
    _ = knowledge_convenience
    _ = knowledge_amazon
    agent.print_response("What are the key features?")


if __name__ == "__main__":
    main()
