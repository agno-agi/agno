"""
Team Brain
==========
One MCP endpoint that the whole team points their AI apps at: everyone writes
decisions into the same log and reads them back out of it. The author of a
decision is taken from the token the client authenticated with, so a caller
cannot log a decision as someone else.

Running this file serves the AgentOS on http://localhost:7777
MCP Server on http://localhost:7777/mcp

It prints one token per teammate on the way up. Paste one into an MCP client and
ask it to remember something, then paste the other into a second client and ask
what was decided.
"""

import time
from typing import Optional
from uuid import uuid4

from agno.agent import Agent
from agno.db.schemas.service_accounts import ServiceAccount
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, MCPServerConfig
from agno.os.service_accounts import DEFAULT_SERVICE_ACCOUNT_SCOPES, generate_token
from agno.os.settings import AgnoAPISettings

DECISION_LOG = "decisions.md"

# ---------------------------------------------------------------------------
# Storage: one shared decision log for the whole team
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/team_brain.db")
fs = FileSystem(db, namespace="team-brain")

# ---------------------------------------------------------------------------
# Create the Librarian
# ---------------------------------------------------------------------------
librarian = Agent(
    id="librarian",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[fs.tools(read_only=True)],
    instructions=[
        f"The team decision log is {DECISION_LOG}. Read it before you answer.",
        "Answer only from the log, and quote the line you used including who decided it.",
        "If the log says nothing about the question, say so.",
        fs.instructions(read_only=True),
    ],
)


# ---------------------------------------------------------------------------
# The MCP surface: remember and recall
# ---------------------------------------------------------------------------
async def remember(decision: str, user_id: Optional[str] = None) -> str:
    """Record a decision in the team log."""
    if user_id is None:
        return "Refused: this tool needs an authenticated caller."
    # The log is one decision per line and the name is the end of the line, so the
    # decision itself is collapsed to a single line: text a caller sends cannot
    # become a second line wearing someone else's name.
    text = " ".join(decision.split())
    if not text:
        return "Refused: a decision cannot be empty."
    line = f"- {text} (decided by {user_id})"
    fs.append(DECISION_LOG, line, unique=True)
    return f"Logged: {line}"


async def recall(question: str) -> str:
    """Answer a question from the team decision log."""
    run = await librarian.arun(question)
    return run.content or ""


# ---------------------------------------------------------------------------
# Tokens: one per teammate, verified by the OS
# ---------------------------------------------------------------------------
def issue_token(name: str) -> str:
    """Mint a token for one teammate, replacing the token issued on the previous run."""
    existing = db.get_service_account_by_name(name)
    if existing is not None:
        db.update_service_account(
            existing["id"], revoked_at=int(time.time()), return_record=False
        )
    plaintext, token_hash, token_prefix = generate_token()
    account = ServiceAccount(
        id=str(uuid4()),
        name=name,
        token_hash=token_hash,
        token_prefix=token_prefix,
        scopes=list(DEFAULT_SERVICE_ACCOUNT_SCOPES),
    )
    db.create_service_account(account.to_dict())
    return plaintext


# ---------------------------------------------------------------------------
# Create the AgentOS
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    id="team-brain",
    db=db,
    agents=[librarian],
    # Tokens are only verified when the OS has authentication on; the security key turns it on.
    settings=AgnoAPISettings(os_security_key="team-brain-admin-key"),
    # user_id is dropped from the schema the client sees and filled from the caller's token.
    mcp_server=MCPServerConfig(tools=[remember, recall], enable_builtin_tools=False),
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run the AgentOS - one token per teammate, then serve
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    for teammate in ["alice", "bob"]:
        print(f"{teammate} token: {issue_token(teammate)}")

    agent_os.serve(app="team_brain:app", reload=True)
