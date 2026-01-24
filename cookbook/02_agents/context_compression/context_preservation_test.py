"""
Context preservation test - validates that compression preserves critical data.

This cookbook tests context compression WITHOUT external tools to isolate
the compression behavior. It injects facts via user messages and verifies
they survive compression.

Run: .venvs/demo/bin/python cookbook/02_agents/context_compression/context_preservation_test.py
"""

from agno.agent import Agent
from agno.compression.manager import CompressionManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat

# Create compression manager - trigger after just 4 messages for quick testing
compression_manager = CompressionManager(
    model=OpenAIChat(id="gpt-5-mini"),
    compress_context=True,
    compress_context_messages_limit=4,
)

agent = Agent(
    model=OpenAIChat(id="gpt-5-mini"),
    description="Financial analyst assistant",
    instructions=[
        "You are a financial analyst assistant.",
        "Always reference specific numbers when answering questions.",
        "Be precise with data - never round or approximate.",
    ],
    compression_manager=compression_manager,
    db=SqliteDb(db_file="tmp/dbs/context_preservation.db"),
    session_id="preservation_test_001",
    add_history_to_context=True,
    num_history_runs=10,
    markdown=True,
)

# Critical facts to inject and verify preservation
TEST_FACTS = {
    "apple_revenue": "$85.78B",
    "apple_profit": "$21.45B",
    "apple_pe": "28.3",
    "msft_revenue": "$62.02B",
    "msft_profit": "$22.29B",
    "msft_pe": "34.7",
    "order_id": "#ORD-2024-98765",
    "customer_id": "CUST-12345-XYZ",
}

# Conversation that injects facts
turns = [
    # Turn 1: Inject Apple facts
    f"""I have Apple's Q4 2024 financial data:
    - Revenue: {TEST_FACTS['apple_revenue']}
    - Net Profit: {TEST_FACTS['apple_profit']}
    - P/E Ratio: {TEST_FACTS['apple_pe']}

    Please acknowledge and summarize these numbers.""",

    # Turn 2: Inject Microsoft facts
    f"""Now here's Microsoft's Q4 2024 data:
    - Revenue: {TEST_FACTS['msft_revenue']}
    - Net Profit: {TEST_FACTS['msft_profit']}
    - P/E Ratio: {TEST_FACTS['msft_pe']}

    Compare Microsoft's profit margin to Apple's.""",

    # Turn 3: Inject order/customer IDs
    f"""I also need help tracking an order:
    - Order ID: {TEST_FACTS['order_id']}
    - Customer ID: {TEST_FACTS['customer_id']}

    Please note these for later reference.""",

    # Turn 4: This should trigger compression - then test retrieval
    """Now I need you to recall ALL the financial data and IDs I shared.

    Please list:
    1. Apple's exact revenue, profit, and P/E ratio
    2. Microsoft's exact revenue, profit, and P/E ratio
    3. The order ID and customer ID

    Use the EXACT numbers I provided - no rounding.""",
]


def check_fact_preservation(response_content: str, facts: dict) -> dict:
    """Check which facts are preserved in the response."""
    results = {}
    for name, value in facts.items():
        # Check if the exact value appears in response
        preserved = value in response_content
        results[name] = {"value": value, "preserved": preserved}
    return results


def run_test():
    print("=" * 70)
    print("CONTEXT PRESERVATION TEST")
    print("=" * 70)
    print("\nThis test validates that exact values survive compression:")
    print(f"  - Financial figures: {TEST_FACTS['apple_revenue']}, {TEST_FACTS['msft_revenue']}")
    print(f"  - IDs: {TEST_FACTS['order_id']}, {TEST_FACTS['customer_id']}")
    print("\nCompression triggers after 4 non-system messages.\n")

    final_response = None

    for i, prompt in enumerate(turns, 1):
        print(f"\n{'='*70}")
        print(f"TURN {i}")
        print("=" * 70)

        # Run the turn
        response = agent.run(prompt, stream=False)
        final_response = response.content

        # Show response summary
        if response.content:
            preview = response.content[:200] + "..." if len(response.content) > 200 else response.content
            print(f"\nResponse preview: {preview}")

        # Check compression stats
        stats = compression_manager.stats
        if stats.get("context_compressions", 0) > 0:
            print("\n[Compression active]")
            print(f"  Total compressions: {stats.get('context_compressions', 0)}")
            print(f"  Messages compressed: {stats.get('messages_compressed', 0)}")

    # Final check - verify fact preservation in the last response
    print("\n" + "=" * 70)
    print("FACT PRESERVATION RESULTS")
    print("=" * 70)

    if final_response:
        results = check_fact_preservation(final_response, TEST_FACTS)

        preserved_count = sum(1 for r in results.values() if r["preserved"])
        total_count = len(results)

        print(f"\nPreserved: {preserved_count}/{total_count} facts\n")

        for name, result in results.items():
            status = "PASS" if result["preserved"] else "FAIL"
            print(f"  [{status}] {name}: {result['value']}")

        if preserved_count == total_count:
            print("\n[SUCCESS] All critical facts were preserved through compression!")
        else:
            print("\n[WARNING] Some facts were lost or modified during compression.")
            print("Check the compression prompt or model behavior.")

    # Show final compressed context
    session = agent.get_session()
    if session:
        ctx = session.get_compression_context()
        if ctx:
            print("\n" + "-" * 70)
            print("FINAL COMPRESSED CONTEXT:")
            print("-" * 70)
            print(ctx.content)
            print(f"\nMessages compressed: {len(ctx.message_ids)}")


if __name__ == "__main__":
    run_test()
