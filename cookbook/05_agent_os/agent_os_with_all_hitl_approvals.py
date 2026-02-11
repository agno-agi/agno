"""AgentOS with all HITL approval types.

Uses the composable @approval decorator from agno.approval with every HITL type:
  1. Confirmation  -- @approval (default type="required") auto-sets requires_confirmation
  2. User Input    -- @approval + @tool(requires_user_input=True, user_input_fields=[...])
  3. External Exec -- @approval + @tool(external_execution=True)

Each tool pauses the run AND creates an approval record. The resolve endpoint
accepts status, resolved_by, and resolution_data (for user_input: pass responses
or modified tool args; for external_execution: pass result).

---

Run:
  .venvs/demo/bin/python cookbook/05_agent_os/agent_os_with_all_hitl_approvals.py

Then visit http://localhost:7770/docs for the Swagger UI.
"""

import json

from agno.agent import Agent
from agno.approval import approval
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.tools import tool


# ---------------------------------------------------------------------------
# 1. CONFIRMATION + APPROVAL
#    @approval (type="required") auto-sets requires_confirmation if no other HITL flag.
# ---------------------------------------------------------------------------


@approval
@tool
def delete_user_account(user_id: str) -> str:
    """Permanently delete a user account and all associated data.

    Args:
        user_id (str): The ID of the user to delete.

    Returns:
        str: Confirmation message.
    """
    return f"User {user_id} and all associated data have been permanently deleted."


@approval
@tool
def revoke_api_keys(user_id: str) -> str:
    """Revoke all API keys for a user, effective immediately.

    Args:
        user_id (str): The user whose keys should be revoked.

    Returns:
        str: Confirmation message.
    """
    return f"All API keys for user {user_id} have been revoked."


# ---------------------------------------------------------------------------
# 2. USER INPUT + APPROVAL
#    @approval + @tool(requires_user_input=True, user_input_fields=[...]).
#    Resolve with resolution_data={"values": {"field": "value"}} to pass input.
# ---------------------------------------------------------------------------


@approval
@tool(requires_user_input=True, user_input_fields=["to_account"])
def transfer_funds(from_account: str, amount: float, to_account: str) -> str:
    """Transfer funds between accounts. The agent decides 'from_account' and
    'amount' based on the conversation; the human provides 'to_account'.

    Args:
        from_account (str): Source account ID.
        amount (float): Amount to transfer.
        to_account (str): Destination account ID (provided by human).

    Returns:
        str: Transfer confirmation.
    """
    return f"Transferred ${amount:.2f} from {from_account} to {to_account}."


@approval
@tool(requires_user_input=True, user_input_fields=["recipient_email"])
def send_report(report_name: str, recipient_email: str) -> str:
    """Generate and send a report via email. The agent picks the report;
    the human provides the recipient email address.

    Args:
        report_name (str): Name of the report to generate.
        recipient_email (str): Email address to send the report to (provided by human).

    Returns:
        str: Delivery confirmation.
    """
    return f"Report '{report_name}' sent to {recipient_email}."


# ---------------------------------------------------------------------------
# 3. EXTERNAL EXECUTION + APPROVAL
#    @approval + @tool(external_execution=True). Resolve with
#    resolution_data={"result": "..."} to pass the external execution result.
# ---------------------------------------------------------------------------


@approval
@tool(external_execution=True)
def deploy_to_production(service_name: str, version: str) -> str:
    """Deploy a service to the production environment.
    Execution happens externally (e.g. via a CI/CD pipeline).

    Args:
        service_name (str): The service to deploy.
        version (str): The version tag to deploy.

    Returns:
        str: Deployment result (provided by the external executor).
    """
    # This body is only used as a fallback; normally the external result is used.
    return f"Deployed {service_name}:{version} to production."


@approval
@tool(external_execution=True, external_execution_silent=True)
def run_database_migration(migration_id: str) -> str:
    """Run a database migration. Executed externally by a DBA or migration tool.
    Silent mode suppresses verbose paused messages.

    Args:
        migration_id (str): The migration identifier to run.

    Returns:
        str: Migration result (provided by the external executor).
    """
    return f"Migration {migration_id} completed."


# ---------------------------------------------------------------------------
# 4. REGULAR TOOL (no approval, no HITL) -- for contrast
# ---------------------------------------------------------------------------


@tool
def get_account_info(account_id: str) -> str:
    """Look up account information (no approval needed).

    Args:
        account_id (str): The account ID.

    Returns:
        str: JSON with account info.
    """
    return json.dumps(
        {
            "account_id": account_id,
            "owner": "Jane Doe",
            "balance": 12500.00,
            "status": "active",
        }
    )


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

db = SqliteDb(
    db_file="tmp/agent_os_all_hitl.db",
    session_table="agent_sessions",
    approvals_table="approvals_new",
)

# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

ops_agent = Agent(
    name="Ops Agent",
    id="ops-agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[
        # Confirmation + approval
        delete_user_account,
        revoke_api_keys,
        # User input + approval
        transfer_funds,
        send_report,
        # External execution + approval
        deploy_to_production,
        run_database_migration,
        # Regular (no HITL)
        get_account_info,
    ],
    instructions=[
        "You are an operations agent for a SaaS platform.",
        "When asked to perform an action, call the appropriate tool immediately.",
        "Do not ask for confirmation yourself -- the system handles approvals automatically.",
        "For account lookups, use get_account_info directly (no approval needed).",
    ],
    markdown=True,
    db=db,
)

# ---------------------------------------------------------------------------
# AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="all-hitl-approvals-demo",
    description="AgentOS with all HITL approval types (confirmation, user input, external execution)",
    agents=[ops_agent],
    db=db,
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="agent_os_with_all_hitl_approvals:app", port=7779)
