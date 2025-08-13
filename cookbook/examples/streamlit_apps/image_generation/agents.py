# Recipe agent for image generation
from textwrap import dedent
from typing import Optional

from agno.agent import Agent
from agno.document.reader.pdf_reader import PDFImageReader
from agno.embedder.cohere import CohereEmbedder
from agno.knowledge.pdf import PDFKnowledgeBase
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.models.groq import Groq
from agno.tools.openai import OpenAITools
from agno.vectordb.pgvector import PgVector

# Database connection string for recipe knowledge base
# Adjust as needed for your environment
DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Constants for recipe agent
DEFAULT_RECIPE_URL = "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
DEFAULT_RECIPE_TABLE = "recipe_documents"


def get_recipe_agent(
    local_pdf_path: Optional[str] = None,
) -> Agent:
    """
    Returns a RecipeImageAgent backed by a recipe PDF knowledge base.
    """
    # Choose the appropriate knowledge base
    if local_pdf_path:
        knowledge_base = PDFKnowledgeBase(
            path=local_pdf_path,
            reader=PDFImageReader(),
            vector_db=PgVector(
                db_url=DB_URL,
                table_name=DEFAULT_RECIPE_TABLE,
                embedder=CohereEmbedder(id="embed-v4.0"),
            ),
        )
    else:
        knowledge_base = PDFUrlKnowledgeBase(
            urls=[DEFAULT_RECIPE_URL],
            vector_db=PgVector(
                db_url=DB_URL,
                table_name=DEFAULT_RECIPE_TABLE,
                embedder=CohereEmbedder(id="embed-v4.0"),
            ),
        )

    model = Groq(id="meta-llama/llama-4-scout-17b-16e-instruct")

    # Instantiate and return the recipe agent
    return Agent(
        name="RecipeImageAgent",
        model=model,
        knowledge=knowledge_base,
        tools=[OpenAITools(image_model="gpt-image-1")],
        instructions=[
            dedent("""\
            You are a specialized recipe assistant.
            When asked for a recipe:
            1. Use the `search_knowledge_base` tool to find and load the most relevant recipe from the knowledge base.
            2. Extract and output exactly two formatted markdown sections:
               ## Ingredients
               - List each ingredient with a hyphen and space prefix.
               ## Directions
               1. Describe each cooking step succinctly, numbering steps starting at 1.
            3. After listing the Directions, invoke the `generate_image` tool exactly once, passing the entire recipe text and using a prompt like '<DishName>: a step-by-step visual guide showing all steps in one overhead image with bright natural lighting. In the prompt make sure to include the all the recipe ingredients and directions that were listed in the Ingredients and Directions sections.'.
            4. Maintain a consistent visual style across the image.
            5. After the image is generated, conclude with 'Recipe generation complete.'
        """),
        ],
        markdown=True,
        debug_mode=True,
    )
