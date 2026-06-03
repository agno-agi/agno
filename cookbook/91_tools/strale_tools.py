"""
Strale Tools - Compliance, KYB, and Financial Validation.

This example demonstrates how to use StraleTools with Agno.
It shows how to use both:
1. Free capabilities (no API key required) like IBAN validation and email validation.
2. Paid/Enterprise capabilities (requires STRALE_API_KEY) like company search and sanctions screening.

Run: `pip install straleio agno`
"""

import os
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.strale import StraleTools

# ---------------------------------------------------------------------------
# Example 1: Free Tier Agent (No API key required)
# Uses IBAN and Email validation
# ---------------------------------------------------------------------------
free_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        StraleTools(
            enable_validate_iban=True,
            enable_validate_email=True,
            enable_lookup_company=False,
            enable_check_sanctions=False,
        )
    ],
    description="You are a compliance assistant specializing in validating financial data and customer contacts.",
    instructions=[
        "Use the validate_iban tool to check if bank accounts are valid.",
        "Use the validate_email tool to check if emails are deliverable.",
        "Respond with structured explanations of the validation status.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Example 2: Enterprise Agent (Requires STRALE_API_KEY)
# Uses Company search and Sanctions screening
# ---------------------------------------------------------------------------
# Check if API key is present for the paid example
api_key = os.getenv("STRALE_API_KEY")

enterprise_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        StraleTools(
            api_key=api_key,
            enable_validate_iban=False,
            enable_validate_email=False,
            enable_lookup_company=True,
            enable_check_sanctions=True,
        )
    ],
    description="You are an enterprise risk and KYB (Know Your Business) analyst.",
    instructions=[
        "Use the lookup_company tool to find company registry details.",
        "Use the check_sanctions tool to run sanctions screenings for people or organizations.",
        "Summarize registration data and screen potential matches for risk.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agents
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Example 1: Free Tier Capabilities (No API Key Required) ===")

    # 1. Financial validation (IBAN)
    print("\n[Testing IBAN Validation]")
    free_agent.print_response("Verify this IBAN: DE89370400440532013000", stream=True)

    # 2. Email verification
    print("\n[Testing Email Verification]")
    free_agent.print_response("Check if contact@strale.dev is a valid email address.", stream=True)

    print("\n=== Example 2: Enterprise Capabilities (Requires STRALE_API_KEY) ===")
    if not api_key:
        print("\n[WARNING] STRALE_API_KEY environment variable is not set.")
        print("To run the enterprise agent example, please set the key:")
        print("export STRALE_API_KEY='your_strale_api_key'\n")
    else:
        # 1. KYB Company Lookup
        print("\n[Testing KYB Company Lookup]")
        enterprise_agent.print_response("Lookup company registry details for 'Stripe' in GB.", stream=True)

        # 2. Sanctions Screening
        print("\n[Testing Sanctions Screening]")
        enterprise_agent.print_response("Screen 'John Doe' from US against sanctions lists.", stream=True)
