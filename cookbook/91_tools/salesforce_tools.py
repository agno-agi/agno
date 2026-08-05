"""
Salesforce CRM Agent that can query, create, update, and manage records using the Salesforce REST API.

Prerequisites:
    1. Install: ``pip install simple-salesforce``
    2. Get a Salesforce org:
       - Sign up free at https://developer.salesforce.com/signup
       - Verify your email and set a password
    3. Get your security token:
       - Log into Salesforce > click avatar (top right) > Settings
       - Left sidebar: "Reset My Security Token" > click "Reset Security Token"
       - Token will be emailed to you
    4. Set environment variables:
       ```
       export SALESFORCE_USERNAME=you@example.com
       export SALESFORCE_PASSWORD=your-password
       export SALESFORCE_SECURITY_TOKEN=token-from-email
       export SALESFORCE_DOMAIN=login
       ```

    If you get "SOAP API login() is disabled", use session-based auth instead:
       ```python
       SalesforceTools(
           instance_url="https://your-org.my.salesforce.com",
           session_id="your-session-id",
       )
       ```
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.salesforce import SalesforceTools

# Read-only agent (default — query, search, and metadata only)
read_only_agent = Agent(
    name="Salesforce Explorer",
    model=OpenAIChat(id="gpt-4o"),
    tools=[SalesforceTools()],
    description="You are a Salesforce data specialist that can explore objects, query records, and search across the org.",
    instructions=[
        "Use describe_object to understand available fields before building queries.",
        "Use SOQL for precise structured queries, SOSL for full-text search across objects.",
        "When listing objects, focus on queryable standard objects unless asked about custom ones.",
    ],
    markdown=True,
)

# Full CRM agent with write operations enabled
full_crm_agent = Agent(
    name="Salesforce CRM Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        SalesforceTools(
            enable_create_record=True,
            enable_update_record=True,
            enable_delete_record=True,
        )
    ],
    description="You are a Salesforce CRM assistant with full read and write capabilities.",
    instructions=[
        "Always use describe_object to check required fields before creating records.",
        "Confirm with the user before deleting any records.",
        "When updating records, show the current values before applying changes.",
    ],
    markdown=True,
)

if __name__ == "__main__":
    # Explore available objects
    read_only_agent.print_response(
        "List the queryable Salesforce objects in this org",
        stream=True,
    )

    # Query accounts
    read_only_agent.print_response(
        "Find the top 5 accounts by name using SOQL",
        stream=True,
    )

    # Describe an object's schema
    read_only_agent.print_response(
        "Describe the Contact object. What fields are required for creating a new contact?",
        stream=True,
    )

    # Search across objects
    read_only_agent.print_response(
        "Search for anything related to 'United' across all objects",
        stream=True,
    )

    # Create a lead (requires full_crm_agent)
    # full_crm_agent.print_response(
    #     "Create a new lead: John Smith, VP of Engineering at TechCorp, email john@techcorp.com",
    #     stream=True,
    # )

    # Update a record (requires full_crm_agent)
    # full_crm_agent.print_response(
    #     "Update the account 'Acme Corp' to set the industry to 'Technology'",
    #     stream=True,
    # )
