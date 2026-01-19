"""
Visual Recipe Guide
===================

Demonstrates generating visual cooking guides with images.

Prerequisites:
    1. Start PostgreSQL: ./cookbook/scripts/run_pgvector.sh
    2. Load recipes: python scripts/load_recipes.py
    3. Set API keys: GOOGLE_API_KEY, COHERE_API_KEY, OPENAI_API_KEY

Usage:
    python examples/02_visual_guide.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from agent import get_visual_recipe  # noqa: E402

# ============================================================================
# Visual Guide Example
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Recipe Agent - Visual Guide")
    print("=" * 60)

    recipe_name = "pad thai"
    print(f"Recipe: {recipe_name}")
    print()
    print("Generating visual cooking guide...")
    print()

    try:
        result = get_visual_recipe(recipe_name)

        print("RECIPE:")
        print("-" * 40)
        print(result["recipe"])
        print()

        if result["images"]:
            print("GENERATED IMAGES:")
            print("-" * 40)
            for i, image_path in enumerate(result["images"], 1):
                print(f"  {i}. {image_path}")
        else:
            print("No images were generated.")

    except Exception as e:
        print(f"Error: {e}")
