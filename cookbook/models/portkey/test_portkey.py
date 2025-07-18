#!/usr/bin/env python3
"""
Test demonstration script for Portkey integration.

This script provides a simple way to test Portkey functionality
before running the full integration test suite.

Requirements:
- Set PORTKEY_API_KEY environment variable
- Set PORTKEY_VIRTUAL_KEY environment variable
- Install dependencies: pip install agno[portkey]
"""

import asyncio
from os import getenv

from agno.agent import Agent
from agno.models.portkey import Portkey
from agno.tools.yfinance import YFinanceTools


def test_basic_functionality():
    """Test basic Portkey functionality."""
    print("🧪 Testing basic Portkey functionality...")

    agent = Agent(model=Portkey(id="gpt-4o-mini"), markdown=True, telemetry=False)

    response = agent.run("Write a haiku about artificial intelligence")
    print("✅ Basic test passed!")
    print(f"Response: {response.content}")
    return True


def test_tool_usage():
    """Test Portkey with tool usage."""
    print("\n🔧 Testing Portkey with tools...")

    agent = Agent(
        model=Portkey(id="gpt-4o-mini"),
        tools=[YFinanceTools(cache_results=True)],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the current price of AAPL stock?")
    print("✅ Tool usage test passed!")
    print(f"Response: {response.content}")
    return True


async def test_async_functionality():
    """Test async Portkey functionality."""
    print("\n🚀 Testing async Portkey functionality...")

    agent = Agent(model=Portkey(id="gpt-4o-mini"), markdown=True, telemetry=False)

    response = await agent.arun("Explain quantum computing in one sentence")
    print("✅ Async test passed!")
    print(f"Response: {response.content}")
    return True


def main():
    """Run all tests."""
    print("🎯 Portkey Integration Test Demo")
    print("=" * 50)

    # Check environment variables
    if not getenv("PORTKEY_API_KEY"):
        print("❌ Error: PORTKEY_API_KEY environment variable not set")
        return False

    if not getenv("PORTKEY_VIRTUAL_KEY"):
        print("❌ Error: PORTKEY_VIRTUAL_KEY environment variable not set")
        return False

    try:
        # Run sync tests
        test_basic_functionality()
        test_tool_usage()

        # Run async test
        asyncio.run(test_async_functionality())

        print("\n🎉 All tests passed! Portkey integration is working correctly.")
        print("\nNext steps:")
        print("- Run full integration tests: ./scripts/run_model_tests.sh portkey")
        print("- Explore cookbook examples in cookbook/models/portkey/")

        return True

    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        return False


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
