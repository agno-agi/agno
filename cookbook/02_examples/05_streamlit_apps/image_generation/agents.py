from typing import Optional

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.pdf_reader import PDFImageReader
from agno.tools.openai import OpenAITools
from agno.utils.streamlit import get_model_from_id
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

DEFAULT_RECIPE_URL = "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"


def get_recipe_image_agent(
    model_id: str = "openai:gpt-4o",
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    local_pdf_path: Optional[str] = None,
) -> Agent:
    """Get a Recipe Image Generation Agent with Knowledge Base"""

    # Choose the appropriate knowledge base
    if local_pdf_path:
        knowledge = Knowledge(
            name="Recipe Knowledge Base",
            description="Custom uploaded recipe collection",
            vector_db=PgVector(
                db_url=db_url,
                table_name="recipe_image_documents",
                embedder=OpenAIEmbedder(id="text-embedding-3-small"),
            ),
            max_results=3,
        )
        knowledge.add_content(
            name=f"Uploaded Recipe: {local_pdf_path.split('/')[-1]}",
            path=local_pdf_path,
            reader=PDFImageReader(),
            description="Custom uploaded recipe PDF",
        )
    else:
        knowledge = Knowledge(
            name="Recipe Knowledge Base",
            description="Thai recipe collection with step-by-step instructions",
            vector_db=PgVector(
                db_url=db_url,
                table_name="recipe_image_documents",
                embedder=OpenAIEmbedder(id="text-embedding-3-small"),
            ),
            max_results=3,
        )
        knowledge.add_content(
            name="Thai Recipes Collection",
            url=DEFAULT_RECIPE_URL,
            description="Comprehensive Thai recipe book with traditional dishes",
        )

    agent = Agent(
        name="Recipe Image Generator",
        model=get_model_from_id(model_id),
        id="recipe-image-agent",
        user_id=user_id,
        knowledge=knowledge,
        add_history_to_context=True,
        num_history_runs=3,
        session_id=session_id,
        tools=[OpenAITools(image_model="gpt-image-1")],
        instructions="""
            You are a specialized recipe assistant that creates visual cooking guides.
            
            When asked for a recipe:
            1. **Search Knowledge Base**: Use the `search_knowledge_base` tool to find the most relevant recipe
            2. **Format Recipe**: Extract and present the recipe in exactly this format:
            
               ## Ingredients
               - List each ingredient with quantities using bullet points
               
               ## Directions  
               1. Step-by-step numbered instructions
               2. Be clear and concise for each cooking step
               3. Include cooking times and temperatures where relevant
               
            3. **Generate Visual Guide**: After presenting the recipe, use the `generate_image` tool with a prompt like:
               '{Dish Name}: A step-by-step visual cooking guide showing all preparation and cooking steps in one overhead view with bright natural lighting. Include all ingredients and show the progression from raw ingredients to final plated dish.'
               
            4. **Maintain Quality**: 
               - Ensure visual consistency across images
               - Include all ingredients and key steps in the image
               - Use bright, appetizing lighting and overhead perspective
               - Show the complete cooking process in one comprehensive view
               
            5. **Complete the Response**: End with 'Recipe generation complete!'
            
            Keep responses focused, clear, and visually appealing. Always search the knowledge base first before responding.
        """,
        markdown=True,
        debug_mode=True,
    )

    return agent
