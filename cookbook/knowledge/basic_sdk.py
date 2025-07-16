from agno.agent import Agent
from agno.db.postgres.postgres import PostgresDb
from agno.knowledge.cloud_storage.cloud_storage import S3Config
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.arxiv_reader import ArxivReader
from agno.knowledge.reader.base import Reader
from agno.knowledge.reader.json_reader import JSONReader
from agno.knowledge.reader.web_search_reader import WebSearchReader
from agno.knowledge.reader.website_reader import WebsiteReader
from agno.knowledge.reader.wikipedia_reader import WikipediaReader
from agno.vectordb.pgvector import PgVector

# Create Knowledge Instance
contents_db = PostgresDb(
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    knowledge_table="knowledge_contents",
)

# Create Knowledge Instance
knowledge = Knowledge(
    name="Basic SDK Knowledge Base",
    description="Agno 2.0 Knowledge Implementation",
    vector_store=PgVector(
        table_name="vectors", db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"
    ),
    contents_db=contents_db,
)

custom_reader = Reader(name="Custom Reader", description="Custom Reader")
knowledge.add_reader(custom_reader)


print("Use Case 1")
# Add from path to the knowledge base
knowledge.add_content(
    name="CV1",
    path="tmp/cv_1.pdf",
    metadata={"user_tag": "Engineering candidates"},
)

print("Use Case 2")
knowledge.add_contents(
    [
        {
            "name": "CV's",
            "path": "tmp/",
            "metadata": {"user_tag": "Engineering candidates"},
        },
        {
            "name": "Docs",
            "path": "my_documents/",
            "metadata": {"user_tag": "Engineering documents"},
        },
        {
            "name": "JSON",
            "url": "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
            "metadata": {"user_tag": "URL document"},
        },
    ]
)

print("Use Case 3")
knowledge.add_contents(
    name="CV's",
    description="Engineering candidates",
    metadata={"user_tag": "Engineering candidates"},
    paths=["tmp/", "docs/"],
    urls=[
        "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
        "https://forum.vorondesign.com/threads/voron-0-2-r1.2379/",
    ],
)


print("Use Case 4")
# Add from URL to the knowledge base
knowledge.add_content(
    name="Recipes",
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    metadata={"user_tag": "Recipes"},
)

print("Use Case 5")
# Specify a customer reader
knowledge.add_content(
    name="Recipes",
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    metadata={"user_tag": "Recipes"},
    reader=WebsiteReader(),
)

print("Use Case 6")
# Add manual content
knowledge.add_content(
    text_content="Hello world",
    metadata={"user_tag": "Manual Text Document"},
)

print("Use Case 7")
# Add manual JSON content
knowledge.add_content(
    name="Manual JSON Document",
    text_content="""
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
# Add from Wikipedia
knowledge.add_content(
    metadata={"user_tag": "Wikipedia content"},
    topics=["Tesla"],
    reader=WikipediaReader(),
)

print("Use Case 9")
# Add from Arxiv
knowledge.add_content(
    metadata={"user_tag": "Arxiv content"},
    topics=["Carbon Dioxide"],
    reader=ArxivReader(),
)

# print("Use Case 10")
# TODO: We are getting rate limited by DDG
# # Add from Web Search
# knowledge.add_content(
#     metadata={"user_tag": "Web Search content"},
#     topics=["Scott Mountain Bikes"],
#     reader=WebSearchReader(),
# )

# print("Use Case 11")
# # TODO: Implementation on Knowledge class
# # Add from S3
# s3_config = S3Config(
#     bucket_name="agno-public",
#     key="recipes/ThaiRecipes.pdf",
# )

# knowledge.add_content(
#     name="S3",
#     config=s3_config,
#     metadata={"user_tag": "Recipes"},
#     # reader=S3PDFReader(),s
# )


agent = Agent(
    name="My Agent",
    description="Agno 2.0 Agent Implementation",
    knowledge=knowledge,
    search_knowledge=True,
    debug_mode=True,
)

agent.print_response(
    "What can you tell me about Agno?",
    markdown=True,
)
