"""
Check Setup
===========

Verifies all prerequisites are configured correctly before running the tutorial.

Checks:
1. Required Python packages
2. API keys (OPENAI_API_KEY, COHERE_API_KEY)
3. PostgreSQL connection
4. Knowledge base loaded

Usage:
    python scripts/check_setup.py

Run this before running any examples to diagnose setup issues.
"""

import os
import sys
from pathlib import Path

# ============================================================================
# Configuration
# ============================================================================
DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
KNOWLEDGE_TABLE = "recipe_documents"


# ============================================================================
# Check Functions
# ============================================================================
def check_dependencies() -> bool:
    """Check required Python packages are installed."""
    print("\n1. Checking Python dependencies...")

    required = [
        ("agno", "agno"),
        ("cohere", "cohere"),
        ("psycopg", "psycopg[binary]"),
    ]

    all_installed = True
    for module, package in required:
        try:
            __import__(module)
            print(f"   [OK] {module}")
        except ImportError:
            print(f"   [FAIL] {module} not installed. Run: pip install {package}")
            all_installed = False

    return all_installed


def check_api_keys() -> bool:
    """Verify required API keys are set."""
    print("\n2. Checking API keys...")

    all_set = True

    # OpenAI is required for the model and image generation
    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        print(f"   [OK] OPENAI_API_KEY is set ({openai_key[:8]}...)")
    else:
        print("   [FAIL] OPENAI_API_KEY not set (required for model)")
        print("   -> Run: export OPENAI_API_KEY=your-key")
        all_set = False

    # Cohere is required for embeddings
    cohere_key = os.environ.get("COHERE_API_KEY")
    if cohere_key:
        print(f"   [OK] COHERE_API_KEY is set ({cohere_key[:8]}...)")
    else:
        print("   [FAIL] COHERE_API_KEY not set (required for embeddings)")
        print("   -> Run: export COHERE_API_KEY=your-key")
        print("   -> Get a key at: https://cohere.com/")
        all_set = False

    return all_set


def check_postgres() -> bool:
    """Test database connection."""
    print("\n3. Checking PostgreSQL connection...")
    print(f"   URL: {DB_URL}")

    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(DB_URL)
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            result.fetchone()
        print("   [OK] PostgreSQL connection successful")
        return True
    except ImportError:
        print(
            "   [FAIL] sqlalchemy not installed. Run: pip install sqlalchemy psycopg[binary]"
        )
        return False
    except Exception as e:
        print(f"   [FAIL] Cannot connect to PostgreSQL: {e}")
        print("   -> Run: ./cookbook/scripts/run_pgvector.sh")
        return False


def check_knowledge() -> bool:
    """Verify knowledge base is loaded."""
    print("\n4. Checking knowledge base...")

    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(DB_URL)

        with engine.connect() as conn:
            # Check if knowledge table exists
            result = conn.execute(
                text(
                    f"""
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_name = '{KNOWLEDGE_TABLE}'
            """
                )
            )
            exists = result.fetchone()[0] > 0

            if not exists:
                print(f"   [FAIL] Knowledge table '{KNOWLEDGE_TABLE}' not found")
                print("   -> Run: python scripts/load_recipes.py")
                return False

            # Check row count
            result = conn.execute(text(f"SELECT COUNT(*) FROM {KNOWLEDGE_TABLE}"))
            count = result.fetchone()[0]

            if count > 0:
                print(f"   [OK] Knowledge base loaded: {count} recipes")
                return True
            else:
                print("   [FAIL] Knowledge base empty (0 recipes)")
                print("   -> Run: python scripts/load_recipes.py")
                return False

    except Exception as e:
        print(f"   [FAIL] Cannot check knowledge base: {e}")
        print("   -> Run: python scripts/load_recipes.py")
        return False


def check_import() -> bool:
    """Verify agent can be imported."""
    print("\n5. Checking agent import...")

    try:
        # Add parent directory to path
        parent_dir = Path(__file__).parent.parent
        if str(parent_dir) not in sys.path:
            sys.path.insert(0, str(parent_dir))

        from agent import recipe_agent  # noqa: F401

        print("   [OK] recipe_agent imported successfully")
        return True
    except Exception as e:
        print(f"   [FAIL] Cannot import agent: {e}")
        return False


# ============================================================================
# Main
# ============================================================================
def main() -> int:
    """Run all setup checks and return exit code."""
    print("=" * 60)
    print("Recipe Agent Tutorial - Setup Check")
    print("=" * 60)

    results = {
        "Dependencies": check_dependencies(),
        "API Keys": check_api_keys(),
        "PostgreSQL": check_postgres(),
        "Knowledge Base": check_knowledge(),
        "Agent Import": check_import(),
    }

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    all_passed = True
    for name, passed in results.items():
        status = "[OK]" if passed else "[FAIL]"
        print(f"   {status} {name}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print("All checks passed! You're ready to run the examples.")
        print()
        print("Try:")
        print("  python examples/01_basic_recipe.py")
        return 0
    else:
        print("Some checks failed. Please fix the issues above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
