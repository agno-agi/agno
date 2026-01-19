"""
Check Setup
===========

Verifies all prerequisites are configured correctly before running the tutorial.

Checks:
1. PostgreSQL connection
2. Required API keys (OPENAI_API_KEY)
3. F1 data tables exist and have data
4. Knowledge base is loaded

Usage:
    python scripts/check_setup.py

Run this before running any examples to diagnose setup issues.
"""

import os
import sys
from pathlib import Path

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))


# ============================================================================
# Configuration
# ============================================================================
DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"

REQUIRED_TABLES = [
    "constructors_championship",
    "drivers_championship",
    "fastest_laps",
    "race_results",
    "race_wins",
]

KNOWLEDGE_TABLE = "sql_agent_knowledge"


# ============================================================================
# Check Functions
# ============================================================================
def check_postgres() -> bool:
    """Test database connection."""
    print("\n1. Checking PostgreSQL connection...")
    print(f"   URL: {DB_URL}")

    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(DB_URL)
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            result.fetchone()
        print("   ✓ PostgreSQL connection successful")
        return True
    except ImportError:
        print(
            "   ✗ sqlalchemy not installed. Run: pip install sqlalchemy psycopg[binary]"
        )
        return False
    except Exception as e:
        print(f"   ✗ Cannot connect to PostgreSQL: {e}")
        print("   → Run: ./cookbook/scripts/run_pgvector.sh")
        return False


def check_api_keys() -> bool:
    """Verify required API keys are set."""
    print("\n2. Checking API keys...")

    all_set = True

    # OpenAI is required for embeddings
    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        print(f"   ✓ OPENAI_API_KEY is set ({openai_key[:8]}...)")
    else:
        print("   ✗ OPENAI_API_KEY not set (required for embeddings)")
        print("   → Run: export OPENAI_API_KEY=your-key")
        all_set = False

    # Anthropic is optional (only if using Claude model)
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        print(f"   ✓ ANTHROPIC_API_KEY is set ({anthropic_key[:8]}...)")
    else:
        print("   ○ ANTHROPIC_API_KEY not set (optional, only needed for Claude model)")

    return all_set


def check_tables() -> bool:
    """Verify F1 tables exist and have data."""
    print("\n3. Checking F1 data tables...")

    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(DB_URL)
        all_exist = True

        with engine.connect() as conn:
            for table in REQUIRED_TABLES:
                try:
                    result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                    count = result.fetchone()[0]
                    if count > 0:
                        print(f"   ✓ {table}: {count:,} rows")
                    else:
                        print(f"   ✗ {table}: empty (0 rows)")
                        all_exist = False
                except Exception:
                    print(f"   ✗ {table}: table not found")
                    all_exist = False

        if not all_exist:
            print("   → Run: python scripts/load_f1_data.py")

        return all_exist
    except Exception as e:
        print(f"   ✗ Cannot check tables: {e}")
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
                print(f"   ✗ Knowledge table '{KNOWLEDGE_TABLE}' not found")
                print("   → Run: python scripts/load_knowledge.py")
                return False

            # Check row count
            result = conn.execute(text(f"SELECT COUNT(*) FROM {KNOWLEDGE_TABLE}"))
            count = result.fetchone()[0]

            if count > 0:
                print(f"   ✓ Knowledge base loaded: {count} documents")
                return True
            else:
                print("   ✗ Knowledge base empty (0 documents)")
                print("   → Run: python scripts/load_knowledge.py")
                return False

    except Exception as e:
        print(f"   ✗ Cannot check knowledge base: {e}")
        print("   → Run: python scripts/load_knowledge.py")
        return False


def check_dependencies() -> bool:
    """Check required Python packages are installed."""
    print("\n5. Checking Python dependencies...")

    required = [
        ("agno", "agno"),
        ("sqlalchemy", "sqlalchemy"),
        ("pandas", "pandas"),
        ("requests", "requests"),
        ("psycopg", "psycopg[binary]"),
    ]

    all_installed = True
    for module, package in required:
        try:
            __import__(module)
            print(f"   ✓ {module}")
        except ImportError:
            print(f"   ✗ {module} not installed. Run: pip install {package}")
            all_installed = False

    return all_installed


# ============================================================================
# Main
# ============================================================================
def main() -> int:
    """Run all setup checks and return exit code."""
    print("=" * 60)
    print("Text-to-SQL Tutorial - Setup Check")
    print("=" * 60)

    results = {
        "Dependencies": check_dependencies(),
        "API Keys": check_api_keys(),
        "PostgreSQL": check_postgres(),
        "F1 Tables": check_tables(),
        "Knowledge Base": check_knowledge(),
    }

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    all_passed = True
    for name, passed in results.items():
        status = "✓" if passed else "✗"
        print(f"   {status} {name}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print("All checks passed! You're ready to run the examples.")
        print()
        print("Try:")
        print("  python examples/basic_queries.py")
        return 0
    else:
        print("Some checks failed. Please fix the issues above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
