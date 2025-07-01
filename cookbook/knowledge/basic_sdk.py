from agno.agent import Agent
from agno.document.document_v2 import DocumentContent, DocumentV2
from agno.document.reader.arxiv_reader import ArxivReader
from agno.document.reader.json_reader import JSONReader
from agno.document.reader.website_reader import WebsiteReader
from agno.knowledge.cloud_storage.cloud_storage import S3Config
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector

# Create Knowledge Instance
knowledge = Knowledge(
    name="Basic SDK Knowledge Base",
    description="Agno 2.0 Knowledge Implementation",
    vector_store=PgVector(
        table_name="vectors", db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"
    ),
)

print("Use Case 1")
# Add from path DocumentV2 to the knowledge base
knowledge.add_document(
    DocumentV2(
        name="CV1",
        path="tmp/cv_1.pdf",
        metadata={"user_tag": "Engineering candidates"},
    )
)

print("Use Case 2")
# Add from URL DocumentV2 to the knowledge base
knowledge.add_document(
    DocumentV2(
        name="Recipes",
        url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
        metadata={"user_tag": "Recipes"},
    )
)

print("Use Case 3")
# Add from path to the knowledge base
knowledge.add_document(
    name="CVs",
    path="tmp/cv_2.pdf",
    metadata={"user_tag": "Engineering candidates"},
)

print("Use Case 4")
# Add from url to the knowledge base
knowledge.add_document(
    name="Recipes",
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    metadata={"user_tag": "Engineering candidates"},
)

print("Use Case 5")
# Specify a customer reader
knowledge.add_document(
    name="Recipes",
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    metadata={"user_tag": "Recipes"},
    reader=WebsiteReader(),
)

print("Use Case 6")
# Add manual content
knowledge.add_document(
    content="Hello world",
    metadata={"user_tag": "Manual Text Document"},
)

print("Use Case 7")
# Add manual JSON content
knowledge.add_document(
    name="Manual JSON Document",
    content="""
    {
        "name": "John Doe",
        "age": 30,
        "email": "john.doe@example.com"
    }
    """,
    metadata={"user_tag": "Manual JSON Document"},
    reader=JSONReader(),
)

print("Use Case 8")
# Add from DocumentV2 Content
knowledge.add_document(
    DocumentV2(
        name="Manual Document Content",
        metadata={"user_tag": "Manual Document Content"},
        content=DocumentContent(
            content="Hello world",
        ),
    )
)

print("Use Case 9")
# Add from DocumentV2 String Content
knowledge.add_document(
    DocumentV2(
        name="Manual Document String Content",
        metadata={"user_tag": "Manual Document String Content"},
        content="""
            All manual content is added to the knowledge base.
        """,
    )
)


print("Use Case 10")
# TODO: We need to add a reader for Wikipedia
# Add from Wikipedia
knowledge.add_document(
    DocumentV2(
        name="Wikipedia Content",
        metadata={"user_tag": "Manual Document String Content"},
        topics=["Real Madrid", "Barcelona"],
        # reader=WikipediaReader(),
    )
)

print("Use Case 11")
# TODO: We need to add a reader for Arxiv
# Add from Arxiv
knowledge.add_document(
    DocumentV2(
        name="Arxiv Content",
        metadata={"user_tag": "Manual Document String Content"},
        topics=["Real Madrid", "Barcelona"],
        # reader=ArxivReader(),
    )
)

print("Use Case 12")
# TODO: We need to add a reader for Web Search
# Add from Web Search
knowledge.add_document(
    DocumentV2(
        name="Web Search Content",
        metadata={"user_tag": "Manual Document String Content"},
        topics=["Real Madrid", "Barcelona"],
        # reader=WebSearchReader(),
    )
)

print("Use Case 13")
# TODO: Implementation on Knowledge class
# Add from S3
s3_config = S3Config(
    bucket_name="agno-public",
    key="recipes/ThaiRecipes.pdf",
)

knowledge.add_document(
    name="S3",
    config=s3_config,
    metadata={"user_tag": "Recipes"},
    # reader=S3PDFReader(),
)
