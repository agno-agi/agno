"""
Slack HITL — Financial Transfer Approval
=========================================

Banking agent that handles money transfers. Transfers require user input
(recipient details) AND admin approval via os.agno.com.

Try in Slack:
  @bot send $500 from checking to my landlord
  @bot transfer $2000 from savings
"""

from typing import Any, Dict, List

from agno.agent import Agent
from agno.approval import approval
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools import tool

_ACCOUNTS: Dict[str, Dict[str, Any]] = {
    "checking": {"balance": 15000.00, "number": "****4521"},
    "savings": {"balance": 45000.00, "number": "****8832"},
    "business": {"balance": 125000.00, "number": "****1199"},
}

_TRANSFER_LOG: List[Dict[str, Any]] = []


@tool
def list_accounts() -> str:
    """List all accounts with balances."""
    lines = [f"  {n}: ${a['balance']:,.2f}" for n, a in _ACCOUNTS.items()]
    return "Accounts:\n" + "\n".join(lines)


@tool
def get_balance(account: str) -> str:
    """Get balance for an account."""
    if account not in _ACCOUNTS:
        return f"Account {account!r} not found."
    return f"{account}: ${_ACCOUNTS[account]['balance']:,.2f}"


@approval
@tool(
    requires_confirmation=True,
    requires_user_input=True,
    user_input_fields=["recipient_name", "recipient_account", "memo"],
)
def send_money(
    amount: float,
    from_account: str,
    recipient_name: str = "",
    recipient_account: str = "",
    memo: str = "",
) -> str:
    """Send money. Requires user input + admin approval."""
    if from_account not in _ACCOUNTS:
        return f"Account {from_account!r} not found."

    account = _ACCOUNTS[from_account]
    if amount > account["balance"]:
        return f"Insufficient funds. Available: ${account['balance']:,.2f}"

    account["balance"] -= amount
    transfer_id = f"TXN{len(_TRANSFER_LOG) + 1:06d}"
    _TRANSFER_LOG.append(
        {
            "id": transfer_id,
            "amount": amount,
            "recipient": recipient_name,
        }
    )

    return (
        f"Transfer {transfer_id}: ${amount:,.2f} to {recipient_name}\n"
        f"New balance: ${account['balance']:,.2f}"
    )


db = SqliteDb(
    db_file="tmp/hitl_financial_approval.db",
    session_table="agent_sessions",
    approvals_table="approvals",
)

agent = Agent(
    name="Banking Assistant",
    id="banking-assistant",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[list_accounts, get_balance, send_money],
    instructions=[
        "You are a banking assistant for transfers.",
        "Check balances before transfers. User provides recipient details in the form.",
    ],
    markdown=True,
)

agent_os = AgentOS(
    description="Slack HITL — financial transfer approval",
    agents=[agent],
    db=db,
    interfaces=[Slack(agent=agent, reply_to_mentions_only=True)],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="hitl_financial_approval:app", reload=True, port=7777)
