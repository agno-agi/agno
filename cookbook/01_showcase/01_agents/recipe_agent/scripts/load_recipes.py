"""
Load Recipes
============

Load recipe PDFs into the knowledge base.

Usage:
    python scripts/load_recipes.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from agent import recipe_knowledge  # noqa: E402


def load_recipes():
    """Load recipe documents into the knowledge base."""
    # Default recipe PDF from Agno public S3
    recipe_url = "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"

    print("Loading recipes into knowledge base...")
    print(f"Source: {recipe_url}")

    recipe_knowledge.add_content(
        name="Thai Recipes Collection",
        url=recipe_url,
    )

    print("Recipes loaded successfully!")


if __name__ == "__main__":
    load_recipes()
