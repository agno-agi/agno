"""
UniRate API Integration Example

This example demonstrates how to use the UniRateTools to get currency exchange
rates, convert amounts between currencies, list supported currencies, and look
up VAT rates via the UniRate API.

Prerequisites:
1. Get a free API key from https://unirateapi.com
2. Set the UNIRATE_API_KEY environment variable or pass it directly to the tool

Usage:
- Get the current exchange rate between two currencies
- Convert an amount from one currency to another
- List all supported currencies
- Look up VAT rates by country
"""

from agno.agent import Agent
from agno.tools.unirate import UniRateTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Example 1: Enable all UniRate functions
agent_all = Agent(
    tools=[
        UniRateTools(
            all=True,  # Enable all UniRate functions
            base_currency="USD",
        )
    ],
    markdown=True,
)

# Example 2: Enable specific UniRate functions only
agent_specific = Agent(
    tools=[
        UniRateTools(
            enable_get_exchange_rate=True,
            enable_convert_currency=True,
            enable_list_currencies=False,
            enable_get_vat_rate=False,
        )
    ],
    markdown=True,
)

# Example 3: Default behavior with all functions enabled
agent = Agent(
    tools=[UniRateTools()],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Example 1: Using all UniRate functions ===")
    agent_all.print_response(
        "Convert 100 US dollars to euros and tell me the current USD to GBP rate.",
        markdown=True,
    )

    print("\n=== Example 2: Currency conversion + exchange rate only ===")
    agent_specific.print_response(
        "How much is 250 EUR in JPY?",
        markdown=True,
    )

    print("\n=== Example 3: Default UniRate agent usage ===")
    agent.print_response(
        "What is the VAT rate in Germany?",
        markdown=True,
    )

    # Additional examples (commented out to avoid API calls)
    # agent.print_response(
    #     "List all the currencies UniRate supports.",
    #     markdown=True,
    # )

    # agent.print_response(
    #     "Convert 1000 CAD to USD and to AUD.",
    #     markdown=True,
    # )
