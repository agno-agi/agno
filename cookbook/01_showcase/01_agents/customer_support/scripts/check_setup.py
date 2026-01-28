"""
Check Setup
===========

Verifies all prerequisites are configured correctly before running the
Customer Support Agent.

Usage:
    python scripts/check_setup.py
"""

import os
import sys
from pathlib import Path


def check_dependencies() -> bool:
    """Check required Python packages are installed."""
    print("\n1. Checking Python dependencies...")

    required = [
        ("agno", "agno"),
        ("openai", "openai"),
        ("ddgs", "ddgs"),
        ("lancedb", "lancedb"),
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

    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        print(f"   [OK] OPENAI_API_KEY is set ({openai_key[:8]}...)")
    else:
        print("   [FAIL] OPENAI_API_KEY not set (required for GPT model and embeddings)")
        print("   -> Run: set OPENAI_API_KEY=your-key (Windows)")
        print("   -> Or:  export OPENAI_API_KEY=your-key (Unix)")
        all_set = False

    # Optional keys
    for key, desc in [
        ("LINEAR_API_KEY", "Linear ticket management"),
        ("SLACK_BOT_TOKEN", "Slack notifications"),
        ("ZENDESK_SUBDOMAIN", "Zendesk knowledge base"),
    ]:
        val = os.environ.get(key)
        if val:
            print(f"   [OK] {key} is set")
        else:
            print(f"   [INFO] {key} not set (optional, for {desc})")

    return all_set


def check_knowledge_base() -> bool:
    """Verify knowledge base files exist."""
    print("\n3. Checking knowledge base...")

    manual_path = Path(__file__).parent.parent / "manual" / "support_manual.txt"
    if manual_path.exists():
        size = manual_path.stat().st_size
        print(f"   [OK] support_manual.txt ({size:,} bytes)")
        return True
    else:
        print(f"   [FAIL] support_manual.txt not found at {manual_path}")
        return False


def check_tools() -> bool:
    """Verify tools are available."""
    print("\n4. Checking tools...")

    try:
        from agno.tools.linear import LinearTools
        from agno.tools.slack import SlackTools
        from agno.tools.websearch import WebSearchTools
        from agno.tools.zendesk import ZendeskTools

        print(f"   [OK] {WebSearchTools.__name__} available")
        print(f"   [OK] {LinearTools.__name__} available")
        print(f"   [OK] {ZendeskTools.__name__} available")
        print(f"   [OK] {SlackTools.__name__} available")
        return True
    except ImportError as e:
        print(f"   [FAIL] Could not import tools: {e}")
        return False


def check_agent_import() -> bool:
    """Verify agent can be imported."""
    print("\n5. Checking agent import...")

    try:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from agent import customer_support_agent
        print("   [OK] customer_support_agent imported successfully")
        print(f"   -> Agent name: {customer_support_agent.name}")
        print(f"   -> Model: {customer_support_agent.model.id}")
        return True
    except ImportError as e:
        print(f"   [FAIL] Could not import agent: {e}")
        return False
    except Exception as e:
        print(f"   [FAIL] Error initializing agent: {e}")
        return False


def main():
    """Run all setup checks."""
    print("=" * 60)
    print("Customer Support Agent - Setup Check")
    print("=" * 60)

    results = {
        "Dependencies": check_dependencies(),
        "API Keys": check_api_keys(),
        "Knowledge Base": check_knowledge_base(),
        "Tools": check_tools(),
        "Agent Import": check_agent_import(),
    }

    print("\n" + "=" * 60)
    print("SETUP CHECK SUMMARY")
    print("=" * 60)

    all_passed = all(results.values())
    for check, passed in results.items():
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {status} {check}")

    print()
    if all_passed:
        print("All checks passed! You're ready to use the Customer Support Agent.")
        print("\nTry running:")
        print("  python agent.py")
        print("  python examples/run_examples.py")
    else:
        print("Some checks failed. Please fix the issues above and try again.")

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
