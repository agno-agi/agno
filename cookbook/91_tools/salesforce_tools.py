"""
Salesforce CRM Tools
=============================

Demonstrates Salesforce CRM tools for account, contact, lead,
and opportunity management via the Salesforce REST API.

Requirements:
    - ``simple-salesforce`` library (``pip install simple-salesforce``)
    - Set environment variables (pick one auth method):

      **Option A** — Username / Password (requires SOAP API enabled in the org):
          - ``SALESFORCE_USERNAME``
          - ``SALESFORCE_PASSWORD``
          - ``SALESFORCE_SECURITY_TOKEN``
          - ``SALESFORCE_DOMAIN`` (``login`` for production, ``test`` for sandbox)

      **Option B** — Session / Instance URL (works in all orgs):
          - Pass ``instance_url`` and ``session_id`` directly.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.salesforce import SalesforceTools


# Example 1: Read-only CRM explorer (default — safe for any agent)

explorer_agent = Agent(
    name="Salesforce Explorer",
    model=OpenAIChat(id="gpt-4o"),
    tools=[SalesforceTools()],
    instructions=[
        "You are a Salesforce data explorer.",
        "Use describe_object to understand fields before querying.",
        "Use SOQL for precise queries, SOSL for full-text search.",
    ],
    markdown=True,
)


# Example 2: Sales pipeline agent (read + create + update)

sales_agent = Agent(
    name="Sales Pipeline Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        SalesforceTools(
            enable_create_record=True,
            enable_update_record=True,
        )
    ],
    instructions=[
        "You are a sales operations assistant.",
        "Help manage accounts, contacts, leads, and opportunities in Salesforce.",
        "Always use describe_object first to understand available fields before creating or updating records.",
    ],
    markdown=True,
)


# Example 3: Full admin agent (all operations including delete)

admin_agent = Agent(
    name="Salesforce Admin",
    model=OpenAIChat(id="gpt-4o"),
    tools=[SalesforceTools(all=True)],
    instructions=[
        "You are a Salesforce administrator.",
        "You can perform any CRM operation including creating, updating, and deleting records.",
        "Always confirm destructive actions before proceeding.",
    ],
    markdown=True,
)


# Example 4: Read-only agent with custom limits

compact_agent = Agent(
    name="Compact Explorer",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        SalesforceTools(
            max_records=50,
            max_fields=30,
        )
    ],
    instructions=["You are a focused CRM analyst. Return concise results."],
    markdown=True,
)


# Run examples

if __name__ == "__main__":
    print("--- Example 1: Discover objects in the org ---")
    explorer_agent.print_response(
        "What Salesforce objects are available? Show me the first 10 queryable ones."
    )

    print("\n--- Example 2: Query accounts ---")
    explorer_agent.print_response("Find the top 5 accounts by name using SOQL.")

    print("\n--- Example 3: Describe an object ---")
    explorer_agent.print_response(
        "Describe the Contact object. What fields are available?"
    )

    print("\n--- Example 4: Search across objects ---")
    explorer_agent.print_response(
        "Search for anything related to 'United' across all objects."
    )

    # Uncomment to test write operations (creates a real Lead in your org):
    # sales_agent.print_response(
    #     "Create a new lead: John Smith, VP of Engineering at TechCorp, email john@techcorp.com"
    # )
