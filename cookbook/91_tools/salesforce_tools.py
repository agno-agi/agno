"""
Salesforce CRM Tools
=============================

Demonstrates Salesforce CRM tools for account, contact, lead,
and opportunity management via the Salesforce REST API.

Requirements:
    - ``simple-salesforce`` library
    - Set environment variables:
        - ``SALESFORCE_USERNAME``: Your Salesforce username
        - ``SALESFORCE_PASSWORD``: Your Salesforce password
        - ``SALESFORCE_SECURITY_TOKEN``: Your security token
        - ``SALESFORCE_DOMAIN``: ``login`` (production) or ``test`` (sandbox)
"""

from agno.agent import Agent
from agno.tools.salesforce import SalesforceTools

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------

# Example 1: Full CRM agent with all operations
agent_full = Agent(
    tools=[SalesforceTools(all=True)],
    markdown=True,
)

# Example 2: Read-only CRM agent (no create/update/delete)
agent_readonly = Agent(
    tools=[
        SalesforceTools(
            enable_list_objects=True,
            enable_describe_object=True,
            enable_get_record=True,
            enable_create_record=False,
            enable_update_record=False,
            enable_delete_record=False,
            enable_query=True,
            enable_search=True,
        )
    ],
    markdown=True,
)

# Example 3: Sales pipeline agent
agent_sales = Agent(
    tools=[
        SalesforceTools(
            enable_list_objects=False,
            enable_describe_object=True,
            enable_get_record=True,
            enable_create_record=True,
            enable_update_record=True,
            enable_delete_record=False,
            enable_query=True,
            enable_search=True,
        )
    ],
    instructions=[
        "You are a sales operations assistant.",
        "Help manage accounts, contacts, leads, and opportunities in Salesforce.",
        "Always use describe_object first to understand available fields before creating or updating records.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Example 1: Discover objects in the org ===")
    agent_full.print_response("List all queryable Salesforce objects", markdown=True)

    print("\n=== Example 2: Query accounts ===")
    agent_readonly.print_response(
        "Find the top 5 accounts by annual revenue",
        markdown=True,
    )

    print("\n=== Example 3: Create a lead ===")
    agent_sales.print_response(
        "Create a new lead: John Smith, VP of Engineering at TechCorp, email john@techcorp.com",
        markdown=True,
    )

    print("\n=== Example 4: Search across objects ===")
    agent_readonly.print_response(
        "Search for anything related to 'Acme' across all objects",
        markdown=True,
    )
