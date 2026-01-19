"""
Evaluate Agent
==============

Note: The Social Media Analyst requires live X/Twitter API access for full testing.
This evaluate script provides basic validation of agent configuration.

For full testing:
- Run the examples with valid X/Twitter credentials
- Verify brand analysis quality manually

Prerequisites:
    1. X/Twitter API credentials set
    2. OPENAI_API_KEY set
    Run: python scripts/check_setup.py

Usage:
    python scripts/evaluate.py
"""

import sys
from pathlib import Path
from typing import Any

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))


# ============================================================================
# Evaluation Functions
# ============================================================================
def test_agent_import(verbose: bool = True) -> dict[str, Any]:
    """Test that the agent can be imported."""
    if verbose:
        print("\n  Testing: agent_import")
        print("  Description: Verify social_media_agent imports correctly")

    try:
        from agent import social_media_agent  # noqa: F401

        if verbose:
            print("  [PASS] social_media_agent imported successfully")
        return {"name": "agent_import", "passed": True}
    except Exception as e:
        if verbose:
            print(f"  [FAIL] Error: {e}")
        return {"name": "agent_import", "passed": False, "error": str(e)}


def test_tools_available(verbose: bool = True) -> dict[str, Any]:
    """Test that X tools are available."""
    if verbose:
        print("\n  Testing: tools_available")
        print("  Description: Verify XTools are configured")

    try:
        from agent import social_media_agent

        # Check that tools are configured
        tools = social_media_agent.tools
        tool_names = [t.__class__.__name__ for t in tools if hasattr(t, "__class__")]

        has_x = any("XTools" in name or "X" in name for name in tool_names)
        has_reasoning = any("Reasoning" in name for name in tool_names)

        if has_x and has_reasoning:
            if verbose:
                print(f"  [PASS] Tools configured: {tool_names}")
            return {"name": "tools_available", "passed": True}
        else:
            if verbose:
                print(f"  [FAIL] Missing tools. Found: {tool_names}")
            return {"name": "tools_available", "passed": False}

    except Exception as e:
        if verbose:
            print(f"  [FAIL] Error: {e}")
        return {"name": "tools_available", "passed": False, "error": str(e)}


def test_schema_import(verbose: bool = True) -> dict[str, Any]:
    """Test that output schema can be imported."""
    if verbose:
        print("\n  Testing: schema_import")
        print("  Description: Verify SocialMediaReport schema imports")

    try:
        from schemas import SocialMediaReport  # noqa: F401

        if verbose:
            print("  [PASS] SocialMediaReport schema imported")
        return {"name": "schema_import", "passed": True}
    except Exception as e:
        if verbose:
            print(f"  [FAIL] Error: {e}")
        return {"name": "schema_import", "passed": False, "error": str(e)}


def run_evaluation(verbose: bool = True) -> dict[str, Any]:
    """Run all test cases and return summary."""
    if verbose:
        print("=" * 60)
        print("Social Media Analyst - Evaluation")
        print("=" * 60)
        print("\nRunning configuration tests...")

    results = [
        test_agent_import(verbose),
        test_tools_available(verbose),
        test_schema_import(verbose),
    ]

    # Calculate summary
    passed = sum(1 for r in results if r["passed"])
    failed = len(results) - passed
    pass_rate = (passed / len(results)) * 100 if results else 0

    summary = {
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "pass_rate": pass_rate,
        "results": results,
    }

    if verbose:
        print("\n" + "=" * 60)
        print("Summary")
        print("=" * 60)
        print(f"\n  Total:     {summary['total']}")
        print(f"  Passed:    {summary['passed']}")
        print(f"  Failed:    {summary['failed']}")
        print(f"  Pass Rate: {summary['pass_rate']:.1f}%")

        if failed > 0:
            print("\n  Failed tests:")
            for r in results:
                if not r["passed"]:
                    error = r.get("error", "See details above")
                    print(f"    - {r['name']}: {error}")

        print(
            """
Note: Full evaluation requires live X/Twitter API access.
Please test with examples/ scripts for complete validation.
"""
        )

    return summary


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("Social Media Analyst - Evaluation Suite")
    print("=" * 60)
    print(
        """
This script tests the social media analyst's configuration.

Note: Full functional testing requires:
  - Valid X/Twitter API credentials
  - Access to Twitter/X API

Tests performed:
  - Agent import
  - Tool configuration
  - Schema validation
"""
    )

    summary = run_evaluation(verbose=True)

    # Exit with appropriate code
    sys.exit(0 if summary["failed"] == 0 else 1)
