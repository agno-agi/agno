"""
Batch Recipe Processing
=======================

Demonstrates processing multiple recipe queries.

Prerequisites:
    1. Start PostgreSQL: ./cookbook/scripts/run_pgvector.sh
    2. Load recipes: python scripts/load_recipes.py
    3. Set API keys: GOOGLE_API_KEY, COHERE_API_KEY

Usage:
    python examples/batch_recipes.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from agent import recipe_agent  # noqa: E402

# ============================================================================
# Batch Processing Example
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Recipe Agent - Batch Processing")
    print("=" * 60)

    queries = [
        "What Thai appetizers can I make?",
        "How do I make tom yum soup?",
        "What desserts are in the collection?",
    ]

    for i, query in enumerate(queries, 1):
        print()
        print(f"Query {i}: {query}")
        print("-" * 40)

        try:
            response = recipe_agent.run(query)
            # Print first 500 chars of response
            content = str(response.content)
            if len(content) > 500:
                print(content[:500] + "...")
            else:
                print(content)
        except Exception as e:
            print(f"Error: {e}")

        print()
