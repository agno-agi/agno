"""
Check Setup
===========

Verifies prerequisites before running the Text-to-SQL agent.

Usage:
    python scripts/check_setup.py
"""

import os
import sys

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"


def check_postgres() -> bool:
    """Test database connection."""
    print("Checking PostgreSQL connection...")
    print(f"  URL: {DB_URL}")

    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(DB_URL)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1")).fetchone()
        print("  ✓ Connected")
        return True
    except ImportError:
        print("  ✗ sqlalchemy not installed")
        print("    Run: pip install sqlalchemy psycopg[binary]")
        return False
    except Exception as e:
        print(f"  ✗ Connection failed: {e}")
        print("    Run: ./cookbook/scripts/run_pgvector.sh")
        return False


def check_api_keys() -> bool:
    """Verify required API keys are set."""
    print("\nChecking API keys...")

    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        print(f"  ✓ OPENAI_API_KEY ({openai_key[:8]}...)")
        return True
    else:
        print("  ✗ OPENAI_API_KEY not set")
        print("    Run: export OPENAI_API_KEY=your-key")
        return False


def main() -> int:
    """Run setup checks."""
    print("=" * 50)
    print("Text-to-SQL Agent - Setup Check")
    print("=" * 50 + "\n")

    postgres_ok = check_postgres()
    api_ok = check_api_keys()

    print("\n" + "=" * 50)
    if postgres_ok and api_ok:
        print("Ready to run.")
        return 0
    else:
        print("Fix the issues above before continuing.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
