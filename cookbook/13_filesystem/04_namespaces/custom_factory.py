"""
Namespaces - Custom Factory
===========================
When a single {user_id} placeholder is not enough, pass a callable instead of
a tools list. The callable picks the namespace with whatever logic you need,
such as roles, tenants or custom keys. It reads the trusted run context, and
its result is cached per user.

This example routes VIP users into their own namespace tier.
"""

from typing import List
from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.models.openai import OpenAIResponses
from agno.run import RunContext

VIP_USERS = {"alice"}

# ---------------------------------------------------------------------------
# Create FileSystem factory
# ---------------------------------------------------------------------------
DB_FILE = f"tmp/agent_fs_factory_{uuid4().hex}.db"

db = SqliteDb(db_file=DB_FILE)


def fs_for_user(run_context: RunContext) -> List:
    # Fail closed on an anonymous run. Without this guard, user_id=None interpolates
    # to "support/standard/None" and every anonymous caller shares one namespace.
    # The factory owns this policy, so a shared anonymous namespace has to be an
    # explicit choice made here rather than something you get by accident.
    if not run_context.user_id:
        raise ValueError(
            "this agent's files require a user_id and none was provided for this run"
        )
    tier = "vip" if run_context.user_id in VIP_USERS else "standard"
    namespace = f"support/{tier}/{run_context.user_id}"
    return [FileSystem(db, namespace=namespace).tools()]


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=fs_for_user,
    instructions="You are a support assistant. Keep your case notes in your files.",
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Note in cases/open.md: alice reported a login issue.", user_id="alice"
    )
    agent.print_response(
        "Note in cases/open.md: carol asked about invoices.", user_id="carol"
    )

    print("namespaces chosen by the factory:")
    vip = FileSystem(db, namespace="support/vip/alice")
    standard = FileSystem(db, namespace="support/standard/carol")
    print("support/vip/alice      ->", repr(vip.read("cases/open.md")))
    print("support/standard/carol ->", repr(standard.read("cases/open.md")))
