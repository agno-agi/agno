"""
OpenRouter Gemini Reasoning Details Test Cookbook

This cookbook demonstrates the reasoning_details feature with Gemini models via OpenRouter.
The reasoning_details field captures Gemini's chain-of-thought reasoning and is preserved
across multi-turn conversations.

This fixes GitHub issue #5849: Gemini 3 Flash with tool use requires reasoning_details preservation.
See: https://openrouter.ai/docs/guides/best-practices/reasoning-tokens#preserving-reasoning-blocks

Key features tested:
1. Basic reasoning_details capture (non-streaming)
2. Streaming mode with reasoning_details
3. Multi-turn conversation with provider_data preservation
4. Tool use with reasoning_details (the original bug from #5849)
5. Debug output showing the full reasoning chain
6. Async variants (arun, async streaming)

Requirements:
- OPENROUTER_API_KEY environment variable set
- OpenRouter account with access to Gemini models

Usage:
    python cookbook/11_models/openrouter/gemini_reasoning_details.py
"""

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openrouter import OpenRouter

# Model ID for Gemini 3 Flash (the model from issue #5849)
GEMINI_MODEL = "google/gemini-3-flash-preview"


def print_separator(title: str) -> None:
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60 + "\n")


def test_basic_reasoning():
    """Test basic reasoning_details capture with non-streaming response."""
    print_separator("TEST 1: Basic Reasoning Details (Non-Streaming)")

    agent = Agent(
        model=OpenRouter(id=GEMINI_MODEL),
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is 15 + 27?")

    print(f"Content: {response.content}")
    print(f"\nHas provider_data: {response.model_provider_data is not None}")

    if response.model_provider_data:
        print(f"Provider data keys: {list(response.model_provider_data.keys())}")

        if "reasoning_details" in response.model_provider_data:
            reasoning = response.model_provider_data["reasoning_details"]
            print("\n[reasoning_details captured]")
            if isinstance(reasoning, str):
                preview = reasoning[:200] + "..." if len(reasoning) > 200 else reasoning
                print(f"Preview: {preview}")
            elif isinstance(reasoning, list) and len(reasoning) > 0:
                print(f"Reasoning items: {len(reasoning)}")
                print(f"First item type: {type(reasoning[0])}")
            else:
                print(f"Reasoning type: {type(reasoning)}")
        else:
            print("\n[No reasoning_details in response]")


def test_streaming_reasoning():
    """Test reasoning_details capture with streaming response."""
    print_separator("TEST 2: Streaming with Reasoning Details")

    agent = Agent(
        model=OpenRouter(id=GEMINI_MODEL),
        markdown=True,
        telemetry=False,
    )

    print("Streaming response...")
    response_stream = agent.run("What is 8 * 7?", stream=True)

    accumulated_content = ""
    reasoning_found_in_chunk = None

    for i, chunk in enumerate(response_stream):
        if chunk.content:
            accumulated_content += chunk.content

        if chunk.model_provider_data and "reasoning_details" in chunk.model_provider_data:
            if reasoning_found_in_chunk is None:
                reasoning_found_in_chunk = i
                print(f"[reasoning_details found in chunk {i}]")

    print(f"\nAccumulated content: {accumulated_content}")
    print(f"Reasoning found in chunk: {reasoning_found_in_chunk}")


def test_multi_turn_preservation():
    """Test that provider_data is preserved across multi-turn conversations."""
    print_separator("TEST 3: Multi-Turn Conversation (Provider Data Preservation)")

    agent = Agent(
        model=OpenRouter(id=GEMINI_MODEL),
        db=InMemoryDb(),
        add_history_to_context=True,
        markdown=True,
        telemetry=False,
    )

    # Turn 1
    print("Turn 1: What is 15 + 27?")
    response1 = agent.run("What is 15 + 27?")
    print(f"Response: {response1.content}")
    print(f"Has provider_data: {response1.model_provider_data is not None}")

    # Turn 2 - references Turn 1
    print("\nTurn 2: Multiply that by 3")
    response2 = agent.run("Multiply that by 3")
    print(f"Response: {response2.content}")
    print(f"Has provider_data: {response2.model_provider_data is not None}")

    # Check all stored messages have provider_data
    print("\n[Checking stored messages...]")
    messages = agent.get_session_messages()
    assistant_messages = [m for m in messages if m.role == "assistant"]

    print(f"Total messages: {len(messages)}")
    print(f"Assistant messages: {len(assistant_messages)}")

    for i, msg in enumerate(assistant_messages):
        has_pd = msg.provider_data is not None
        has_reasoning = (
            msg.provider_data is not None and "reasoning_details" in msg.provider_data
        )
        print(f"  Message {i+1}: provider_data={has_pd}, reasoning_details={has_reasoning}")


def test_detailed_debug():
    """Debug test showing full reasoning_details structure."""
    print_separator("TEST 4: Detailed Debug Output")

    agent = Agent(
        model=OpenRouter(id=GEMINI_MODEL),
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the capital of France?")

    print(f"Content: {response.content}")
    print("\n[Full provider_data structure]")

    if response.model_provider_data:
        for key, value in response.model_provider_data.items():
            if key == "reasoning_details":
                print(f"\n{key}:")
                if isinstance(value, list):
                    for j, item in enumerate(value[:3]):  # Show first 3 items
                        print(f"  [{j}]: {type(item).__name__}")
                        if hasattr(item, "__dict__"):
                            for k, v in vars(item).items():
                                preview = str(v)[:100] + "..." if len(str(v)) > 100 else str(v)
                                print(f"       {k}: {preview}")
                        elif isinstance(item, dict):
                            for k, v in item.items():
                                preview = str(v)[:100] + "..." if len(str(v)) > 100 else str(v)
                                print(f"       {k}: {preview}")
                else:
                    preview = str(value)[:300] + "..." if len(str(value)) > 300 else str(value)
                    print(f"  {preview}")
            elif key == "model_extra":
                print(f"\n{key}: {list(value.keys()) if isinstance(value, dict) else type(value)}")
            else:
                print(f"\n{key}: {value}")


def test_tool_use():
    """
    Test tool use with reasoning_details preservation.

    This is the CRITICAL test for GitHub issue #5849:
    Gemini 3 Flash + tools was broken because reasoning_details weren't preserved.
    """
    print_separator("TEST 5: Tool Use with Reasoning Details (Issue #5849)")

    def get_weather(city: str) -> str:
        """Get the current weather for a city.

        Args:
            city: The city name to get weather for.

        Returns:
            A string describing the weather.
        """
        weather_data = {
            "paris": "Sunny, 22C",
            "london": "Cloudy, 15C",
            "tokyo": "Rainy, 18C",
            "new york": "Clear, 25C",
        }
        return weather_data.get(city.lower(), f"Weather data not available for {city}")

    agent = Agent(
        model=OpenRouter(id=GEMINI_MODEL),
        tools=[get_weather],
        db=InMemoryDb(),
        add_history_to_context=True,
        markdown=True,
        telemetry=False,
    )

    # First turn - should use the tool
    print("Turn 1: What's the weather in Paris?")
    response1 = agent.run("What's the weather in Paris?")
    print(f"Response: {response1.content}")
    print(f"Has provider_data: {response1.model_provider_data is not None}")

    # Second turn - should remember context and potentially use tool again
    print("\nTurn 2: How about London?")
    response2 = agent.run("How about London?")
    print(f"Response: {response2.content}")
    print(f"Has provider_data: {response2.model_provider_data is not None}")

    # Verify messages have provider_data
    print("\n[Checking stored messages...]")
    messages = agent.get_session_messages()
    assistant_messages = [m for m in messages if m.role == "assistant"]

    print(f"Total messages: {len(messages)}")
    print(f"Assistant messages: {len(assistant_messages)}")

    all_have_provider_data = all(m.provider_data is not None for m in assistant_messages)
    print(f"All assistant messages have provider_data: {all_have_provider_data}")

    if all_have_provider_data:
        print("\n[SUCCESS] Tool use with reasoning_details works correctly!")
    else:
        print("\n[ISSUE] Some messages missing provider_data")


def test_multi_turn_tool_use():
    """Test multi-turn conversation with tools - the exact scenario from issue #5849."""
    print_separator("TEST 6: Multi-Turn Tool Use (Extended)")

    def calculate(expression: str) -> str:
        """Evaluate a mathematical expression.

        Args:
            expression: A mathematical expression to evaluate (e.g., '2 + 2').

        Returns:
            The result of the calculation.
        """
        try:
            allowed = set("0123456789+-*/.(). ")
            if all(c in allowed for c in expression):
                result = eval(expression)
                return str(result)
            return "Invalid expression"
        except Exception as e:
            return f"Error: {e}"

    agent = Agent(
        model=OpenRouter(id=GEMINI_MODEL),
        tools=[calculate],
        db=InMemoryDb(),
        add_history_to_context=True,
        markdown=True,
        telemetry=False,
    )

    turns = [
        "Calculate 15 + 27",
        "Now multiply that result by 3",
        "Divide the result by 2",
    ]

    for i, prompt in enumerate(turns, 1):
        print(f"\nTurn {i}: {prompt}")
        response = agent.run(prompt)
        print(f"Response: {response.content}")

        if response.model_provider_data:
            has_reasoning = "reasoning_details" in response.model_provider_data
            print(f"  provider_data: present, reasoning_details: {has_reasoning}")
        else:
            print("  provider_data: MISSING")

    messages = agent.get_session_messages()
    assistant_messages = [m for m in messages if m.role == "assistant"]
    missing_count = sum(1 for m in assistant_messages if m.provider_data is None)

    if missing_count == 0:
        print(f"\n[SUCCESS] All {len(assistant_messages)} assistant messages have provider_data!")
    else:
        print(f"\n[ISSUE] {missing_count}/{len(assistant_messages)} messages missing provider_data")


def test_streaming_with_tools():
    """Test streaming mode with tools."""
    print_separator("TEST 7: Streaming with Tools")

    def multiply(a: int, b: int) -> int:
        """Multiply two numbers.

        Args:
            a: First number.
            b: Second number.

        Returns:
            The product of a and b.
        """
        return a * b

    agent = Agent(
        model=OpenRouter(id=GEMINI_MODEL),
        tools=[multiply],
        markdown=True,
        telemetry=False,
    )

    print("Streaming with tool use...")
    response_stream = agent.run("Multiply 7 by 8", stream=True)

    accumulated_content = ""
    reasoning_found = False

    for chunk in response_stream:
        if chunk.content:
            accumulated_content += chunk.content
        if chunk.model_provider_data and "reasoning_details" in chunk.model_provider_data:
            reasoning_found = True

    print(f"Content: {accumulated_content}")
    print(f"Reasoning found: {reasoning_found}")

    if accumulated_content:
        print("[SUCCESS] Streaming with tools works!")
    else:
        print("[ISSUE] No content accumulated")


async def test_async_basic():
    """Test async non-streaming with reasoning_details."""
    print_separator("TEST 8: Async Basic (Non-Streaming)")

    agent = Agent(
        model=OpenRouter(id=GEMINI_MODEL),
        markdown=True,
        telemetry=False,
    )

    response = await agent.arun("What is 9 + 16?")

    print(f"Content: {response.content}")
    print(f"Has provider_data: {response.model_provider_data is not None}")

    if response.model_provider_data and "reasoning_details" in response.model_provider_data:
        print("[SUCCESS] Async reasoning_details captured!")
    else:
        print("[ISSUE] Missing reasoning_details")


async def test_async_streaming():
    """Test async streaming with reasoning_details."""
    print_separator("TEST 9: Async Streaming")

    agent = Agent(
        model=OpenRouter(id=GEMINI_MODEL),
        markdown=True,
        telemetry=False,
    )

    print("Async streaming response...")
    accumulated_content = ""
    reasoning_found_in_chunk = None
    i = 0

    async for chunk in agent.arun("What is 12 * 4?", stream=True):
        if chunk.content:
            accumulated_content += chunk.content

        if chunk.model_provider_data and "reasoning_details" in chunk.model_provider_data:
            if reasoning_found_in_chunk is None:
                reasoning_found_in_chunk = i
                print(f"[reasoning_details found in chunk {i}]")
        i += 1

    print(f"\nAccumulated content: {accumulated_content}")
    print(f"Reasoning found in chunk: {reasoning_found_in_chunk}")


async def test_async_tool_use():
    """Test async tool use with reasoning_details - async variant of issue #5849."""
    print_separator("TEST 10: Async Tool Use")

    def get_time(timezone: str) -> str:
        """Get current time for a timezone.

        Args:
            timezone: The timezone name (e.g., 'UTC', 'EST', 'PST').

        Returns:
            A string with the current time.
        """
        times = {
            "utc": "14:30 UTC",
            "est": "09:30 EST",
            "pst": "06:30 PST",
        }
        return times.get(timezone.lower(), f"Time not available for {timezone}")

    agent = Agent(
        model=OpenRouter(id=GEMINI_MODEL),
        tools=[get_time],
        db=InMemoryDb(),
        add_history_to_context=True,
        markdown=True,
        telemetry=False,
    )

    print("Turn 1: What time is it in UTC?")
    response1 = await agent.arun("What time is it in UTC?")
    print(f"Response: {response1.content}")
    print(f"Has provider_data: {response1.model_provider_data is not None}")

    print("\nTurn 2: And in PST?")
    response2 = await agent.arun("And in PST?")
    print(f"Response: {response2.content}")
    print(f"Has provider_data: {response2.model_provider_data is not None}")

    messages = agent.get_session_messages()
    assistant_messages = [m for m in messages if m.role == "assistant"]
    all_have_provider_data = all(m.provider_data is not None for m in assistant_messages)

    if all_have_provider_data:
        print(f"\n[SUCCESS] Async tool use works! {len(assistant_messages)} messages with provider_data")
    else:
        print("\n[ISSUE] Some messages missing provider_data")


async def run_async_tests():
    """Run all async tests."""
    await test_async_basic()
    await test_async_streaming()
    await test_async_tool_use()


if __name__ == "__main__":
    import asyncio

    print("\n" + "#" * 60)
    print(" OpenRouter Gemini Reasoning Details Test Suite")
    print(f" Model: {GEMINI_MODEL}")
    print("#" * 60)

    # Sync tests
    test_basic_reasoning()
    test_streaming_reasoning()
    test_multi_turn_preservation()
    test_detailed_debug()
    test_tool_use()
    test_multi_turn_tool_use()
    test_streaming_with_tools()

    # Async tests
    asyncio.run(run_async_tests())

    print_separator("ALL TESTS COMPLETE")
