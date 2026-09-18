"""
Provenrail Integration
======================

Demonstrates recording every Agno tool call into a tamper-evident, independently
verifiable audit trail using a tool hook.

Tracing answers "what did we observe and log?". This answers a different question:
"what can we still prove happened, to someone who does not trust us?". Each tool call is
Ed25519-signed by the agent's own key and hash-chained to its predecessor, so a later
edit, deletion, or reordering of the record is detectable by anyone, with an open-source
verifier and no account.

Key concepts:
- A tool hook is middleware: it receives the tool name, the callable and the arguments,
  invokes the callable, and records the outcome.
- Failures are recorded as evidence too, then re-raised unchanged, so Agno's own error
  handling is untouched.
- Capture never breaks the agent: a recording failure is swallowed rather than raised
  into the tool path.

Honest scope: this proves that whatever was recorded has not been altered. It does not,
and cannot, prove completeness: an agent that never invokes the tool cannot be recorded
by a hook. Provenrail is evidence tooling, not legal advice or a compliance certification.

Setup:
    pip install agno provenrail openai
    export OPENAI_API_KEY=...
    pr quickstart          # writes .provenrail.json (local sink, no account needed)

Verify the result afterwards, trusting neither the agent nor the sink:
    pr verify bundle.json
"""

import provenrail as fr
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from provenrail.integrations.agno import provenrail_tool_hook

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
# Reads .provenrail.json, written once by `pr quickstart`. Records are pushed off-box to
# an append-only sink as they happen, so the process that produced them cannot rewrite
# them afterwards.
fr.configure()


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
def transfer_funds(account: str, amount: int) -> str:
    """Transfer an amount to an account.

    Args:
        account: The destination account identifier.
        amount: The amount to transfer.
    """
    return f"Transferred {amount} to {account}"


def check_balance(account: str) -> str:
    """Return the balance of an account.

    Args:
        account: The account identifier.
    """
    return f"Account {account} balance: 10000"


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """
You are a treasury assistant. Check the balance before moving any funds, and never
transfer more than the available balance.
"""


# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Everything inside the `record` block is captured into one signed, sealed session.
    with fr.record("treasury-agent") as recorder:
        agent = Agent(
            model=OpenAIChat(id="gpt-4o"),
            instructions=instructions,
            tools=[check_balance, transfer_funds],
            tool_hooks=[provenrail_tool_hook(recorder)],
            markdown=True,
        )
        agent.print_response("Move 500 to account LT12, but check the balance first.")

    # On exit the session is sealed and flushed off-box. Export it and check it with the
    # standalone verifier, or open the bundle at provenrail.com/verify, which runs a
    # second, independent verifier implementation entirely in your browser.
    print("\nRecorded. Export and verify with:  pr export && pr verify bundle.json")
