"""Example: Multi-Modal RAG & Image Agent

An agent that uses Llama 4 for multi-modal RAG and OpenAITools to create a visual, step-by-step image manual for a recipe.

Run: `pip install openai agno groq cohere` to install the dependencies
"""

from pathlib import Path

from agno.agent import Agent
from agno.embedder.cohere import CohereEmbedder
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.models.groq import Groq
from agno.tools.openai import OpenAITools
from agno.utils.media import download_image
from agno.vectordb.pgvector import PgVector

knowledge_base = PDFUrlKnowledgeBase(
    urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
    vector_db=PgVector(
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
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
    instructions=[
        "You are a specialized recipe assistant.",
        "When asked for a recipe:",
        "1. Search the knowledge base to retrieve the relevant recipe details.",
        "2. Analyze the retrieved recipe steps carefully.",
        "3. Use the `generate_image` tool to create a visual, step-by-step image manual for the recipe.",
        "4. Present the recipe text clearly and mention that you have generated an accompanying image manual. Add instructions while generating the image.",
    ],
    markdown=True,
    debug_mode=True,
)

agent.print_response(
    "What is the recipe for a Thai curry?",
)

response = agent.run_response
if response.images:
    download_image(response.images[0].url, Path("tmp/recipe_image.png"))
