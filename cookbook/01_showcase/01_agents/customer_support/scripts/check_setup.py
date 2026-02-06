"""
Check Setup
===========

Verifies all prerequisites are configured correctly before running the agent.

Checks:
1. Required Python packages
2. API keys (OPENAI_API_KEY, ZENDESK_*)
3. PostgreSQL connection
4. Knowledge base status

Usage:
    python scripts/check_setup.py
"""

import os
import sys
from pathlib import Path

# ============================================================================
# Configuration
# ============================================================================
DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
KNOWLEDGE_TABLE = "support_knowledge"
KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge"


# ============================================================================
# Check Functions
# ============================================================================
def check_dependencies() -> bool:
    """Check required Python packages are installed."""
    print("\n1. Checking Python dependencies...")

    required = [
        ("agno", "agno"),
        ("sqlalchemy", "sqlalchemy"),
        ("psycopg", "psycopg[binary]"),
        ("requests", "requests"),
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

    # OpenAI is required for the model and embeddings
    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        print(f"   [OK] OPENAI_API_KEY is set ({openai_key[:8]}...)")
    else:
        print("   [FAIL] OPENAI_API_KEY not set (required for model and embeddings)")
        print("   -> Run: export OPENAI_API_KEY=your-key")
        all_set = False

    # Zendesk credentials
    zendesk_user = os.environ.get("ZENDESK_USERNAME")
    zendesk_pass = os.environ.get("ZENDESK_PASSWORD")
    zendesk_company = os.environ.get("ZENDESK_COMPANY_NAME")

    if zendesk_user and zendesk_pass and zendesk_company:
        print(f"   [OK] ZENDESK_USERNAME is set ({zendesk_user})")
        print("   [OK] ZENDESK_PASSWORD is set")
        print(f"   [OK] ZENDESK_COMPANY_NAME is set ({zendesk_company})")
    else:
        if not zendesk_user:
            print("   [WARN] ZENDESK_USERNAME not set")
        if not zendesk_pass:
            print("   [WARN] ZENDESK_PASSWORD not set")
        if not zendesk_company:
            print("   [WARN] ZENDESK_COMPANY_NAME not set")
        print("   -> Zendesk integration requires all three variables")
        print("   -> Run: export ZENDESK_USERNAME=your-email")
        print("   -> Run: export ZENDESK_PASSWORD=your-api-token")
        print("   -> Run: export ZENDESK_COMPANY_NAME=your-subdomain")

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


def check_knowledge_files() -> bool:
    """Check that knowledge documents exist."""
    print("\n4. Checking knowledge files...")

    if not KNOWLEDGE_DIR.exists():
        print(f"   [FAIL] Knowledge directory not found: {KNOWLEDGE_DIR}")
        return False

    json_files = list(KNOWLEDGE_DIR.glob("*.json"))
    if json_files:
        print(f"   [OK] Found {len(json_files)} knowledge files:")
        for f in json_files:
            print(f"      - {f.name}")
        return True
    else:
        print("   [WARN] No .json files found in knowledge directory")
        return True


def check_knowledge_table() -> bool:
    """Verify knowledge base is loaded."""
    print("\n5. Checking knowledge base...")

    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(DB_URL)

        with engine.connect() as conn:
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
                print(f"   [WARN] Knowledge table '{KNOWLEDGE_TABLE}' not found")
                print("   -> Run: python scripts/load_knowledge.py")
                return True

            result = conn.execute(text(f"SELECT COUNT(*) FROM {KNOWLEDGE_TABLE}"))
            count = result.fetchone()[0]

            if count > 0:
                print(f"   [OK] Knowledge base loaded: {count} documents")
                return True
            else:
                print("   [WARN] Knowledge base empty (0 documents)")
                print("   -> Run: python scripts/load_knowledge.py")
                return True

    except Exception as e:
        print(f"   [FAIL] Cannot check knowledge base: {e}")
        return False


def check_import() -> bool:
    """Verify agent can be imported."""
    print("\n6. Checking agent import...")

    try:
        parent_dir = Path(__file__).parent.parent
        if str(parent_dir) not in sys.path:
            sys.path.insert(0, str(parent_dir))

        from advanced.agent import agent  # noqa: F401

        print("   [OK] agent imported successfully")
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
    print("Customer Support Agent - Setup Check")
    print("=" * 60)

    results = {
        "Dependencies": check_dependencies(),
        "API Keys": check_api_keys(),
        "PostgreSQL": check_postgres(),
        "Knowledge Files": check_knowledge_files(),
        "Knowledge Table": check_knowledge_table(),
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
        print("  python basic/simple_query.py")
        return 0
    else:
        print("Some checks failed. Please fix the issues above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
