"""
Check Setup
===========

Verifies all prerequisites are configured correctly before running the agent.

Checks:
1. Required Python packages
2. API keys (GOOGLE_API_KEY)
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
    "sample_nda.txt",
    "Sample_NDA.pdf",
]


# ============================================================================
# Check Functions
# ============================================================================
def check_dependencies() -> bool:
    """Check required Python packages are installed."""
    print("\n1. Checking Python dependencies...")

    required = [
        ("agno", "agno"),
        ("google.genai", "google-genai"),
        ("ddgs", "ddgs"),
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

    # Google API key is required for the model
    google_key = os.environ.get("GOOGLE_API_KEY")
    if google_key:
        print(f"   [OK] GOOGLE_API_KEY is set ({google_key[:8]}...)")
    else:
        print("   [FAIL] GOOGLE_API_KEY not set (required for Gemini model)")
        print("   -> Run: export GOOGLE_API_KEY=your-key")
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
            print(f"   [WARN] {doc} not found (optional)")

    # Check if at least one document exists
    all_docs = list(DOCUMENTS_DIR.glob("*.pdf")) + list(DOCUMENTS_DIR.glob("*.txt"))
    if all_docs:
        print(f"   [OK] Found {len(all_docs)} documents in total")
        all_exist = True
    else:
        print("   [FAIL] No documents found in documents directory")
        all_exist = False

    return all_exist


def check_tools() -> bool:
    """Verify tools and guardrails are available."""
    print("\n4. Checking tools and guardrails...")

    try:
        from agno.tools.reasoning import ReasoningTools
        from agno.tools.websearch import WebSearchTools

        print("   [OK] ReasoningTools available")
        print("   [OK] WebSearchTools available")
    except ImportError as e:
        print(f"   [FAIL] Could not import tools: {e}")
        return False

    try:
        from agno.guardrails import (
            OpenAIModerationGuardrail,
            PIIDetectionGuardrail,
            PromptInjectionGuardrail,
        )

        print("   [OK] PIIDetectionGuardrail available")
        print("   [OK] PromptInjectionGuardrail available")
        print("   [OK] OpenAIModerationGuardrail available")
    except ImportError as e:
        print(f"   [FAIL] Could not import guardrails: {e}")
        return False

    return True


def check_import() -> bool:
    """Verify agent can be imported."""
    print("\n5. Checking agent import...")

    try:
        # Add parent directory to path
        parent_dir = Path(__file__).parent.parent
        if str(parent_dir) not in sys.path:
            sys.path.insert(0, str(parent_dir))

        from agent import contract_agent  # noqa: F401

        print("   [OK] contract_agent imported successfully")
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
    print("Contract Review Agent - Setup Check")
    print("=" * 60)

    results = {
        "Dependencies": check_dependencies(),
        "API Keys": check_api_keys(),
        "Documents": check_documents(),
        "Tools & Guardrails": check_tools(),
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
        print("All checks passed! You're ready to run the agent.")
        print()
        print("Try:")
        print("  python agent.py                    # Interactive CLI")
        print("  python examples/run_examples.py   # Run examples")
        return 0
    else:
        print("Some checks failed. Please fix the issues above and try again.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
