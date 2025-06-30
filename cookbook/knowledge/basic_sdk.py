from agno.agent import Agent
from agno.document.document_v2 import DocumentV2
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

# Add files to the knowledge base
knowledge.add_documents(
    DocumentV2(
        name="CV1",
        path="tmp/cv_1.pdf",
        metadata={"user_tag": "Engineering candidates"},
    )
)

# Add a URL to the knowledge base
knowledge.add_documents(
    DocumentV2(
        name="Recipes",
        url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
        metadata={"user_tag": "Recipes"},
    )
)


knowledge.add_document(
    name="CVs",
    path="tmp/",
    metadata={"user_tag": "Engineering candidates"},
)

knowledge.add_document(
    name="CV1",
    path="tmp/cv_1.pdf",
    metadata={"user_tag": "Engineering candidates"},
)

knowledge.add_document(
    paths=["tmp/cv_1.pdf", "tmp/cv_2.pdf"],
    metadata={"user_tag": "Engineering candidates"},
)

knowledge.add_document(
    name="URL1",
    urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
    metadata={"user_tag": "Recipes"},
    reader=WebsiteReader(),
)

knowledge.add_document(
    content="Hello world",
    metadata={"user_tag": "Manual Document"},
)

knowledge.add_document(
    name="Manual JSON Document",
    content="""
    {
        "name": "John Doe",
        "age": 30,
        "email": "john.doe@example.com"
    }
    """,
    metadata={"user_tag": "Manual Document"},
    reader=JSONReader(),
)


knowledge.add_document(
    DocumentV2(
        name="CV1",
        paths=["tmp/cv_1.pdf", "tmp/cv_2.pdf"],
        metadata={"user_tag": "Engineering candidates"},
    ),
    paths=["tmp/cv_1.pdf", "tmp/cv_2.pdf"],
    metadata={"user_tag": "Engineering candidates"},
)

knowledge.add_document(
    name="Wikipedia",
    topics=[
        "Manchester United",
        "Real Madrid",
    ],  # Throw error if no reader passed when topics are provided
    metadata={"user_tag": "Football"},
    reader=WikipediaReader(),
)

s3_config = S3Config(
    bucket_name="agno-public",
    key="recipes/ThaiRecipes.pdf",
)
azure_config = AzureConfig(
    container_name="agno-public",
    key="recipes/ThaiRecipes.pdf",
)

knowledge.add_document(
    name="S3",
    config=s3_config,
    metadata={"user_tag": "Recipes"},
    reader=S3PDFReader(),
)


# This is only supported with document db
# knowledge.get_document(id="CV1")
# knowledge.get_documents(name="CV")
# knowledge.get_documents(metadata="CV1")


# # Supported with document db and vector db
# knowledge.remove_document(id="CV1")


# knowledge.add_documents(
#     [
#         {
#             "name": "CVs",
#             "path": "tmp/",
#             "metadata": {"user_tag": "Engineering candidates"},
#         },
#         {
#             "name": "URL1",
#             "url": "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
#             "reader": PDFUrlReader(),
#         }
#     ]
# )
