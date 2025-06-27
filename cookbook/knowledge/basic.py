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
# knowledge.add_documents(
#     DocumentV2(
#         name="CV1",
#         paths=["tmp/cv_1.pdf", "tmp/cv_2.pdf"],
#         metadata={"user_tag": "Engineering candidates"},
#     )
# )

# knowledge.add_document(
#     DocumentV2(
#         path="storage/csv/",
#         metadata={"user_tag": "Test"},
#     ),
# )

# Add a file URL to the knowledge base
# knowledge.add_document(
#     DocumentV2(
#         name="Recipe",
#         # url="https://www.youtube.com/watch?v=CDC3GOuJyZ0",
#         url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
#         metadata={"user_tag": "URL sources"},
#     ),
# )

# # Add a youtube URL to the knowledge base
# knowledge.add_document(
#     DocumentV2(
#         name="Youtube Video",
#         url="https://www.youtube.com/watch?v=CDC3GOuJyZ0",
#         metadata={"user_tag": "URL sources"},
#     ),
# )

# Add a generic URL to the knowledge base
knowledge.add_document(
    DocumentV2(
        name="Generic URL",
        url="https://community.agno.com/t/can-agno-work-with-qwen-llm/1391",
        metadata={"user_tag": "URL sources"},
    ),
)


agent = Agent(
    name="My Agent",
    model=OpenAIChat(id="gpt-4o"),
    description="Agno 2.0 Agent Implementation",
    knowledge=knowledge,
    search_knowledge=True,
    debug_mode=True,
)


agent.print_response(
    "What were the latest changes to Agno?",
    markdown=True,
)


# agent.print_response(
#     "What is the expected ripper arm pitch at a roll angle of 4.37?",
#     markdown=True,
# )