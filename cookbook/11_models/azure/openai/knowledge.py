"""Run `pip install ddgs sqlalchemy pgvector pypdf openai` to install dependencies."""

import asyncio

from agno.agent import Agent
from agno.knowledge.embedder.azure_openai import AzureOpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.azure import AzureOpenAI
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge = Knowledge(
    vector_db=PgVector(
        table_name="recipes",
        db_url=db_url,
        embedder=AzureOpenAIEmbedder(),
    ),
)
# Add content to the knowledge
asyncio.run(
    knowledge.add_content_async(
        url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
    )
)

agent = Agent(
    model=AzureOpenAI(id="gpt-4o-mini"),
    knowledge=knowledge,
)
agent.print_response("How to make Thai curry?", markdown=True)
