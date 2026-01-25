"""
Check Setup
===========

Verifies all prerequisites are configured correctly before running the tutorial.

Checks:
1. Required Python packages
2. API keys (OPENAI_API_KEY)
3. Gmail credentials
4. Agent import

Usage:
    python scripts/check_setup.py

Run this before running any examples to diagnose setup issues.
"""

import os
import sys
from pathlib import Path


# ============================================================================
# Check Functions
# ============================================================================
def check_dependencies() -> bool:
    """Check required Python packages are installed."""
    print("\n1. Checking Python dependencies...")

    required = [
        ("agno", "agno"),
        ("google.auth", "google-auth"),
        ("google_auth_oauthlib", "google-auth-oauthlib"),
        ("google_auth_httplib2", "google-auth-httplib2"),
        ("googleapiclient", "google-api-python-client"),
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


def check_gmail_credentials() -> bool:
    """Check for Gmail OAuth credentials."""
    print("\n3. Checking Gmail credentials...")

    # Check for credentials file
    creds_file = Path.home() / ".config" / "agno" / "gmail_credentials.json"
    creds_file_alt = Path("credentials.json")

    if creds_file.exists():
        print(f"   [OK] Gmail credentials found: {creds_file}")
        return True
    elif creds_file_alt.exists():
        print(f"   [OK] Gmail credentials found: {creds_file_alt}")
        return True
    else:
        print("   [FAIL] Gmail credentials not found")
        print("   -> Download OAuth credentials from Google Cloud Console")
        print("   -> Save as ~/.config/agno/gmail_credentials.json")
        print("   -> Or set GMAIL_CREDENTIALS_PATH environment variable")
        return False


def check_gmail_token() -> bool:
    """Check for Gmail OAuth token (indicates prior authorization)."""
    print("\n4. Checking Gmail authorization...")

    token_file = Path.home() / ".config" / "agno" / "gmail_token.json"
    token_file_alt = Path("token.json")

    if token_file.exists() or token_file_alt.exists():
        print("   [OK] Gmail token found (previously authorized)")
        return True
    else:
        print("   [WARN] No Gmail token found")
        print("   -> You will be prompted to authorize on first run")
        return True  # Not a hard failure


def check_import() -> bool:
    """Verify agent can be imported."""
    print("\n5. Checking agent import...")

    try:
        # Add parent directory to path
        parent_dir = Path(__file__).parent.parent
        if str(parent_dir) not in sys.path:
            sys.path.insert(0, str(parent_dir))

        from agent import inbox_agent  # noqa: F401

        print("   [OK] inbox_agent imported successfully")
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
    print("Inbox Agent Tutorial - Setup Check")
    print("=" * 60)

    results = {
        "Dependencies": check_dependencies(),
        "API Keys": check_api_keys(),
        "Gmail Credentials": check_gmail_credentials(),
        "Gmail Token": check_gmail_token(),
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
        print("  python examples/triage_inbox.py")
        return 0
    else:
        print("Some checks failed. Please fix the issues above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
