"""
Check Setup
===========

Verifies all prerequisites are configured correctly before running the
Code Review Agent.

Checks:
1. Required Python packages
2. API keys (OPENAI_API_KEY, GITHUB_TOKEN)
3. Optional tools availability

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
EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


# ============================================================================
# Check Functions
# ============================================================================
def check_dependencies() -> bool:
    """Check required Python packages are installed."""
    print("\n1. Checking Python dependencies...")

    required = [
        ("agno", "agno"),
        ("openai", "openai"),
        ("github", "PyGithub"),
        ("ddgs", "ddgs"),
        ("bs4", "beautifulsoup4"),
    ]

    all_required_installed = True

    # Check required packages
    for module, package in required:
        try:
            __import__(module)
            print(f"   [OK] {module}")
        except ImportError:
            print(f"   [FAIL] {module} not installed. Run: pip install {package}")
            all_required_installed = False

    return all_required_installed


def check_api_keys() -> bool:
    """Verify required API keys are set."""
    print("\n2. Checking API keys...")

    all_set = True

    # OpenAI API key is required for the model
    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        print(f"   [OK] OPENAI_API_KEY is set ({openai_key[:8]}...)")
    else:
        print("   [FAIL] OPENAI_API_KEY not set (required for GPT model)")
        print("   -> Run: set OPENAI_API_KEY=your-key (Windows)")
        print("   -> Or:  export OPENAI_API_KEY=your-key (Unix)")
        all_set = False

    # Anthropic API key is optional (for Claude Opus 4.5 alternative)
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        print(f"   [OK] ANTHROPIC_API_KEY is set ({anthropic_key[:8]}...)")
        print("   -> Claude Opus 4.5 is available as an alternative model")
    else:
        print("   [INFO] ANTHROPIC_API_KEY not set (optional)")
        print(
            "   -> Set this if you want to use Claude Opus 4.5 instead of GPT-5.2-Codex"
        )
        print("   -> Get key: https://console.anthropic.com/")

    # GitHub token is optional but recommended
    github_token = os.environ.get("GITHUB_TOKEN")
    if github_token:
        print(f"   [OK] GITHUB_TOKEN is set ({github_token[:8]}...)")
    else:
        print("   [WARN] GITHUB_TOKEN not set (optional, needed for PR fetching)")
        print("   -> Run: set GITHUB_TOKEN=your-token (Windows)")
        print("   -> Or:  export GITHUB_TOKEN=your-token (Unix)")
        print("   -> Get token: https://github.com/settings/tokens")

    return all_set


def check_agent_import() -> bool:
    """Verify agent can be imported."""
    print("\n3. Checking agent import...")

    try:
        # Add parent directory to path
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from agent import code_review_agent

        print("   [OK] code_review_agent imported successfully")
        print(f"   -> Agent name: {code_review_agent.name}")
        print(f"   -> Model: {code_review_agent.model.id}")
        return True
    except ImportError as e:
        print(f"   [FAIL] Could not import agent: {e}")
        return False
    except Exception as e:
        print(f"   [FAIL] Error initializing agent: {e}")
        return False


def check_tools() -> bool:
    """Verify tools are available."""
    print("\n4. Checking tools...")

    try:
        from agno.tools.file import FileTools
        from agno.tools.github import GithubTools
        from agno.tools.python import PythonTools
        from agno.tools.reasoning import ReasoningTools
        from agno.tools.shell import ShellTools
        from agno.tools.websearch import WebSearchTools
        from agno.tools.website import WebsiteTools

        print(f"   [OK] {GithubTools.__name__} available")
        print(f"   [OK] {ReasoningTools.__name__} available")
        print(f"   [OK] {WebSearchTools.__name__} available")
        print(f"   [OK] {ShellTools.__name__} available")
        print(f"   [OK] {FileTools.__name__} available")
        print(f"   [OK] {PythonTools.__name__} available")
        print(f"   [OK] {WebsiteTools.__name__} available")
        return True
    except ImportError as e:
        print(f"   [FAIL] Could not import tools: {e}")
        return False


def print_summary(results: dict) -> None:
    """Print a summary of all checks."""
    print("\n" + "=" * 60)
    print("SETUP CHECK SUMMARY")
    print("=" * 60)

    all_passed = all(results.values())

    for check, passed in results.items():
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {status} {check}")

    print()
    if all_passed:
        print("All checks passed! You're ready to use the Code Review Agent.")
        print("\nTry running:")
        print("  python agent.py")
        print("  python examples/run_examples.py")
    else:
        print("Some checks failed. Please fix the issues above and try again.")
        print("\nFor installation help, see README.md")

    print()


def main():
    """Run all setup checks."""
    print("=" * 60)
    print("Code Review Agent - Setup Check")
    print("=" * 60)

    results = {
        "Dependencies": check_dependencies(),
        "API Keys": check_api_keys(),
        "Tools": check_tools(),
        "Agent Import": check_agent_import(),
    }

    print_summary(results)

    # Exit with appropriate code
    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    main()
