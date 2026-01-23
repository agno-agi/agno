"""
Multi-Modal Recipe Agent
========================

A multi-modal RAG agent that retrieves recipes from a knowledge base
and generates step-by-step visual instruction manuals using image generation.

Example prompts:
- "What is the recipe for Thai green curry?"
- "Show me how to make pad thai with pictures"
- "Give me a visual guide for making chocolate cake"

Usage:
    from agent import recipe_agent, get_visual_recipe

    # Interactive mode
    recipe_agent.print_response("Thai curry recipe", stream=True)

    # Get visual recipe
    result = get_visual_recipe("pad thai")
"""

from pathlib import Path

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.tools.openai import OpenAITools
from agno.tools.reasoning import ReasoningTools
from agno.vectordb.pgvector import PgVector, SearchType

# ============================================================================
# Database Configuration
# ============================================================================
DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# ============================================================================
# Knowledge Base Setup
# ============================================================================
recipe_knowledge = Knowledge(
    name="Recipe Knowledge Base",
    vector_db=PgVector(
        db_url=DB_URL,
        table_name="recipe_documents",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    max_results=5,
)

# ============================================================================
# System Message
# ============================================================================
SYSTEM_MESSAGE = """\
You are a specialized recipe assistant with access to a recipe knowledge base
and image generation capabilities.

## Your Responsibilities

1. **Recipe Retrieval** - Search the knowledge base for relevant recipes
2. **Clear Instructions** - Present recipes in a clear, step-by-step format
3. **Visual Guides** - Generate helpful images for key cooking steps
4. **Adaptations** - Suggest modifications for dietary restrictions

## Workflow

When asked for a recipe:

1. **Search** - Use the knowledge base to find the relevant recipe
2. **Present** - Format the recipe with:
   - Ingredients list with quantities
   - Step-by-step instructions
   - Tips and variations
3. **Visualize** - Generate images for 2-3 key cooking steps:
   - Ingredient preparation (chopping, measuring)
   - Key cooking technique (stir-frying, simmering)
   - Final plated dish

## Image Generation Guidelines

When generating images:
- Use descriptive prompts that capture the cooking step
- Request food photography style images
- Focus on the most visually instructive steps
- Include relevant ingredients and cookware in the scene

Example image prompts:
- "Professional food photography of Thai green curry ingredients laid out on a wooden cutting board, fresh vegetables, coconut milk, curry paste"
- "Overhead shot of a wok with stir-fried vegetables and tofu, steam rising, professional food photography"
- "Beautifully plated Thai green curry in a white bowl with jasmine rice, garnished with basil leaves, food photography"

## Response Format

### [Recipe Name]

**Prep Time:** X minutes
**Cook Time:** X minutes
**Servings:** X

#### Ingredients
- Item 1
- Item 2
...

#### Instructions
1. Step 1
2. Step 2
...

#### Tips
- Tip 1
- Tip 2

Use the think tool to plan your recipe presentation and image generation.
"""


# ============================================================================
# Create the Agent
# ============================================================================
recipe_agent = Agent(
    name="Recipe Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    system_message=SYSTEM_MESSAGE,
    knowledge=recipe_knowledge,
    tools=[
        OpenAITools(),
        ReasoningTools(add_instructions=True),
    ],
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    enable_agentic_memory=True,
    search_knowledge=True,
    markdown=True,
    db=SqliteDb(db_file="tmp/data.db"),
)


# ============================================================================
# Helper Functions
# ============================================================================
def get_visual_recipe(query: str, save_images: bool = True) -> dict:
    """Get a recipe with visual guide.

    Args:
        query: Recipe query (e.g., "Thai green curry").
        save_images: Whether to save generated images to disk.

    Returns:
        Dictionary with recipe text and image paths.
    """
    response = recipe_agent.run(
        f"Please find the recipe for {query} and generate visual guides for the key steps."
    )

    result = {
        "recipe": response.content,
        "images": [],
    }

    if response.images and save_images:
        from agno.utils.media import download_image

        output_dir = Path("tmp/recipes")
        output_dir.mkdir(parents=True, exist_ok=True)

        for i, image in enumerate(response.images):
            image_path = output_dir / f"{query.replace(' ', '_')}_{i + 1}.png"
            if image.url:
                download_image(image.url, image_path)
                result["images"].append(str(image_path))

    return result


# ============================================================================
# Exports
# ============================================================================
__all__ = [
    "recipe_agent",
    "recipe_knowledge",
    "get_visual_recipe",
]

if __name__ == "__main__":
    recipe_agent.cli_app(stream=True)
