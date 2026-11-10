"""
ServiceNow Tools
=============================

Demonstrates ServiceNow ITSM tools for incident and change management.

Requirements:
    - ``requests`` library
    - Set environment variables:
        - ``SERVICENOW_INSTANCE``: Your instance name (e.g. ``dev12345``)
        - ``SERVICENOW_USERNAME``: Username for basic auth
        - ``SERVICENOW_PASSWORD``: Password for basic auth
"""

from agno.agent import Agent
from agno.tools.servicenow import ServiceNowTools

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------

# Example 1: Enable all ServiceNow functions
agent_all = Agent(
    tools=[ServiceNowTools(all=True)],
    markdown=True,
)

# Example 2: Read-only incident agent
agent_readonly = Agent(
    tools=[
        ServiceNowTools(
            enable_get_incident=True,
            enable_query_incidents=True,
            enable_create_incident=False,
            enable_update_incident=False,
            enable_add_comment=False,
            enable_get_change_request=False,
            enable_create_change_request=False,
            enable_query_table=False,
        )
    ],
    markdown=True,
)

# Example 3: Incident management agent
agent_incidents = Agent(
    tools=[
        ServiceNowTools(
            enable_get_incident=True,
            enable_create_incident=True,
            enable_update_incident=True,
            enable_query_incidents=True,
            enable_add_comment=True,
            enable_get_change_request=False,
            enable_create_change_request=False,
            enable_query_table=False,
        )
    ],
    markdown=True,
)

# Example 4: Change management agent
agent_changes = Agent(
    tools=[
        ServiceNowTools(
            enable_get_incident=False,
            enable_create_incident=False,
            enable_update_incident=False,
            enable_query_incidents=False,
            enable_add_comment=False,
            enable_get_change_request=True,
            enable_create_change_request=True,
            enable_query_table=True,
        )
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Example 1: Query all open incidents ===")
    agent_all.print_response("Find all open high-priority incidents", markdown=True)

    print("\n=== Example 2: Read-only incident lookup ===")
    agent_readonly.print_response("Get details for incident INC0010001", markdown=True)

    print("\n=== Example 3: Create an incident ===")
    agent_incidents.print_response(
        "Create a new high-urgency incident: Email server is down affecting all users",
        markdown=True,
    )

    print("\n=== Example 4: Create a change request ===")
    agent_changes.print_response(
        "Create a normal change request to upgrade the database server to version 16",
        markdown=True,
    )
