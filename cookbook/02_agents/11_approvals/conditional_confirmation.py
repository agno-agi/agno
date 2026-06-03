"""
Conditional Confirmation
=============================

Demonstrates the new callable-form `requires_confirmation` for argument-dependent HITL.

Instead of an all-or-nothing static bool, the same tool can pause for risky
arguments and run silently for safe ones. The callable receives the
`FunctionCall` and returns a bool.

Use case: a `delete_file` tool that is safe in /tmp but must be confirmed
anywhere else.
"""

from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools import FunctionCall, tool


# ---------------------------------------------------------------------------
# Tool with conditional confirmation
# ---------------------------------------------------------------------------


def _is_risky_path(fc: FunctionCall) -> bool:
    """Return True (→ require confirmation) for paths outside /tmp.

    This is the whole point of the feature: a single tool, two HITL policies
    based on actual arguments.
    """
    path = fc.arguments.get("path", "")
    return not path.startswith("/tmp/")


@tool(requires_confirmation=_is_risky_path)
def delete_file(path: str) -> str:
    """Delete a file at the given path. Confirmation required if outside /tmp/."""
    p = Path(path)
    if not p.exists():
        return f"Not found: {path}"
    p.unlink()
    return f"Deleted: {path}"


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIChat(id="gpt-5-mini"),
    tools=[delete_file],
    instructions="You are a file cleanup assistant. Delete files when asked.",
    markdown=True,
)


# ---------------------------------------------------------------------------
# Demo: two calls, same tool, different HITL outcomes
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Prep: create two files, one in /tmp, one outside
    safe_file = Path("/tmp/agno_demo_safe.txt")
    risky_file = Path("/tmp/../tmp_demo/agno_demo_risky.txt")
    safe_file.write_text("safe")
    risky_file.parent.mkdir(exist_ok=True, parents=True)
    risky_file.write_text("risky")

    # ---------- Run 1: safe path → NO pause expected ----------
    print("--- Run 1: delete /tmp file (safe, no confirmation) ---")
    r = agent.run(f"Please delete the file at {safe_file}")
    print(f"Run status: {r.status}")
    assert not r.is_paused, (
        "Expected to run without pause (safe path), but got paused — "
        "the callable should have returned False for /tmp paths."
    )
    print(f"Result: {r.content[:200]}")

    # ---------- Run 2: risky path → pause expected ----------
    print("\n--- Run 2: delete file outside /tmp (risky, confirmation required) ---")
    r = agent.run(f"Please delete the file at {risky_file}")
    print(f"Run status: {r.status}")
    assert r.is_paused, (
        "Expected paused (risky path), but got completed — "
        "the callable should have returned True for paths outside /tmp."
    )

    # Simulate user approval
    print("[User] Approving the risky deletion...")
    for req in r.active_requirements:
        if req.needs_confirmation:
            req.confirm()

    r = agent.continue_run(run_response=r)
    print(f"Run status after continue: {r.status}")
    print(f"Final result: {r.content[:200]}")

    # Cleanup
    if risky_file.parent.exists():
        risky_file.parent.rmdir() if not list(risky_file.parent.iterdir()) else None

    print("\n--- Done. Same tool, two different HITL outcomes based on arguments. ---")
