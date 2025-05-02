from typing import Optional
import os

from agno.agent import Agent
from agno.models.groq import Groq
from agno.embedder.cohere import CohereEmbedder
from agno.storage.agent.postgres import PostgresAgentStorage
from agno.vectordb.pgvector import PgVector
from agno.tools.openai import OpenAITools
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.utils.media import download_image
from pathlib import Path
# Database URL for Postgres vectordb and agent storage
DB_URL = os.getenv("RAG_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai")

knowledge_base = PDFUrlKnowledgeBase(
    urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
    vector_db=PgVector(
        db_url=DB_URL,
        table_name="embed_vision_documents",
        embedder=CohereEmbedder(
            id="embed-v4.0",
        ),
    ),
)

knowledge_base.load()

agent = Agent(
    name="EmbedVisionRAGAgent",
    model=Groq(id="meta-llama/llama-4-scout-17b-16e-instruct"),
    tools=[OpenAITools()],
    knowledge=knowledge_base,
    storage=PostgresAgentStorage(
        db_url=DB_URL,
        table_name="embed_vision_rag_sessions"
    ),
    # show_tool_calls=True,
    add_history_to_messages=True,
    markdown=True,
    instructions=[
        "You are a specialized recipe assistant.",
        "When asked for a recipe:",
        "1. Search the knowledge base to retrieve the relevant recipe details.",
        "2. Analyze the retrieved recipe steps carefully.",
        "3. Use the `generate_image` tool to create a visual, step-by-step image manual for the recipe.",
        "4. Present the recipe text clearly and mention that you have generated an accompanying image manual. Add instructions while generating the image.",
    ],
    debug_mode=True,
)

response = agent.run("What is the recipe for a Thai curry?",)

if response.images:
    download_image(response.images[0].url, Path("tmp/recipe_image.png"))
