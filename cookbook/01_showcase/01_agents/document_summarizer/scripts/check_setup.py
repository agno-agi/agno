"""
Check Setup
===========

Verifies all prerequisites are configured correctly before running the tutorial.

Checks:
1. Required Python packages
2. API keys (OPENAI_API_KEY)
3. Sample documents exist

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
DOCUMENTS_DIR = Path(__file__).parent.parent / "documents"

REQUIRED_DOCUMENTS = [
    "meeting_notes.txt",
    "blog_post.md",
]


# ============================================================================
# Check Functions
# ============================================================================
def check_dependencies() -> bool:
    """Check required Python packages are installed."""
    print("\n1. Checking Python dependencies...")

    required = [
        ("agno", "agno"),
        ("pypdf", "pypdf"),
        ("requests", "requests"),
        ("bs4", "beautifulsoup4"),
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

    # OpenAI is required for the model
    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        print(f"   [OK] OPENAI_API_KEY is set ({openai_key[:8]}...)")
    else:
        print("   [FAIL] OPENAI_API_KEY not set (required for model)")
        print("   -> Run: export OPENAI_API_KEY=your-key")
        all_set = False

    return all_set


def check_documents() -> bool:
    """Verify sample documents exist."""
    print("\n3. Checking sample documents...")

    all_exist = True

    if not DOCUMENTS_DIR.exists():
        print(f"   [FAIL] Documents directory not found: {DOCUMENTS_DIR}")
        return False

    for doc in REQUIRED_DOCUMENTS:
        doc_path = DOCUMENTS_DIR / doc
        if doc_path.exists():
            size = doc_path.stat().st_size
            print(f"   [OK] {doc} ({size:,} bytes)")
        else:
            print(f"   [FAIL] {doc} not found")
            all_exist = False

    return all_exist


def check_import() -> bool:
    """Verify agent can be imported."""
    print("\n4. Checking agent import...")

    try:
        # Add parent directory to path
        parent_dir = Path(__file__).parent.parent
        if str(parent_dir) not in sys.path:
            sys.path.insert(0, str(parent_dir))

        from agent import summarizer_agent  # noqa: F401

        print("   [OK] summarizer_agent imported successfully")
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
    print("Document Summarizer Tutorial - Setup Check")
    print("=" * 60)

    results = {
        "Dependencies": check_dependencies(),
        "API Keys": check_api_keys(),
        "Documents": check_documents(),
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
        print("  python examples/01_basic_summary.py")
        return 0
    else:
        print("Some checks failed. Please fix the issues above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
