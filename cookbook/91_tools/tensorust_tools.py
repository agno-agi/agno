"""
Tensorust Tools
=============================

Demonstrates ownership, credit and compliance lookups from US public records
through the Tensorust Ontology.

Tensorust is keyless by default: with no TENSORUST_API_KEY set, every tool
returns a free preview and these examples run as-is. Set TENSORUST_API_KEY
(a tdk_... key) to get the full records instead of the preview.
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.tensorust import TensorustTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Example 1: default TensorustTools, no API key needed
agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[TensorustTools()],
    instructions=[
        "You answer due-diligence questions about US companies from public records.",
        "Cite the data source and the as-of date the tools return.",
        "Say when an answer is a preview and more detail needs a Tensorust key.",
    ],
    markdown=True,
)

# Example 2: with an explicit API key, for the full records
# agent_keyed = Agent(tools=[TensorustTools(api_key="tdk_...")])

# Example 3: only the screening tool, for a vendor onboarding agent
screening_agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[
        TensorustTools(
            enable_lookup_organization=False,
            enable_who_owns_home=False,
            enable_get_lender_marks=False,
            enable_get_contractor_credit=False,
            enable_screen_counterparty=True,
        )
    ],
    markdown=True,
)

# Example 4: every tool, including No Surprises Act arbitration data
agent_all = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[TensorustTools(all=True)],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 80)
    print("OWNERSHIP")
    print("=" * 80)

    agent.print_response(
        "Who controls Invitation Homes, and how many subsidiaries does it have?"
    )

    print("\n" + "=" * 80)
    print("PRIVATE CREDIT")
    print("=" * 80)

    agent.print_response(
        "What do private credit lenders mark Pluralsight's first-lien loan at?"
    )

    print("\n" + "=" * 80)
    print("SCREENING")
    print("=" * 80)

    screening_agent.print_response(
        "We want to buy security cameras from Hikvision with a federal grant. "
        "Screen the vendor and tell me which rules apply."
    )

    print("\n" + "=" * 80)
    print("ASYNC")
    print("=" * 80)

    # agent.aprint_response() runs the toolkit's async variants
    asyncio.run(
        agent_all.aprint_response(
            "How often do providers win federal IDR disputes for CPT 99284 against "
            "UnitedHealthcare in Texas?"
        )
    )
