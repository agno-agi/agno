"""
Basic Recipe Query
==================

Demonstrates basic recipe retrieval from the knowledge base.

Prerequisites:
    1. Start PostgreSQL: ./cookbook/scripts/run_pgvector.sh
    2. Load recipes: python scripts/load_recipes.py
    3. Set API keys: GOOGLE_API_KEY, COHERE_API_KEY

Usage:
    python examples/basic_recipe.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from agent import recipe_agent  # noqa: E402

# ============================================================================
# Basic Recipe Query Example
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Recipe Agent - Basic Query")
    print("=" * 60)

    query = "What is the recipe for Thai green curry?"
    print(f"Query: {query}")
    print()
    print("Searching recipes...")
    print()

    recipe_agent.print_response(query, stream=True)
