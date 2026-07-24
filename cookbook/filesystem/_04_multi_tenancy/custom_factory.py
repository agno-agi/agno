"""
Multi-Tenancy - Custom Factory
==============================

When one placeholder is not enough, a callable tool factory picks the
namespace with arbitrary logic - roles, tenants, custom keys - resolved per
run from the trusted run context, and cached per user.

This example routes VIP users into their own namespace tier.
"""

from typing import List
from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.fs.db import DbFileSystem
from agno.models.openai import OpenAIResponses
from agno.run import RunContext

VIP_USERS = {"alice"}

# ---------------------------------------------------------------------------
# Create FileSystem factory
# ---------------------------------------------------------------------------
DB_FILE = f"tmp/agent_fs_factory_{uuid4().hex}.db"

db_fs = DbFileSystem(db=SqliteDb(db_file=DB_FILE))


def fs_for_user(run_context: RunContext) -> List:
    # Fail closed on an anonymous run. Without this guard, user_id=None interpolates
    # to "support/standard/None" and every anonymous caller shares one namespace. A
    # factory owns its own anonymous policy — here we refuse; another policy might
    # route to an explicit shared "anon" namespace, but never by accident.
    if not run_context.user_id:
        raise ValueError(
            "this agent's files require a user_id and none was provided for this run"
        )
    tier = "vip" if run_context.user_id in VIP_USERS else "standard"
    namespace = f"support/{tier}/{run_context.user_id}"
    return [FileSystem(backend=db_fs, namespace=namespace).tools()]


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
    vip = FileSystem(backend=db_fs, namespace="support/vip/alice")
    standard = FileSystem(backend=db_fs, namespace="support/standard/carol")
    print("support/vip/alice      ->", repr(vip.read("cases/open.md")))
    print("support/standard/carol ->", repr(standard.read("cases/open.md")))
