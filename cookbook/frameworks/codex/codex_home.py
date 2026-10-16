"""
CodexAgent: Own Home Directory
==============================
Run Codex under a scratch CODEX_HOME so the run stays out of your personal
Codex history.

By default the app-server writes every thread to ~/.codex/sessions, the same
place your interactive sessions go. codex_home points this agent at its own
home. The script snapshots your personal session list before the run and fails
if that list changed.

The scratch home needs its own login. With OPENAI_API_KEY exported the script
logs the scratch home in through the agent on first use. Otherwise log in once:

    CODEX_HOME=tmp/harnesses/codex/home codex login

See README.md for setup.
"""

import os
from pathlib import Path

from agno.agents.codex import CodexAgent

# ---------------------------------------------------------------------------
# Configure the Example
# ---------------------------------------------------------------------------
workspace = Path(__file__).resolve().parents[1] / "sample_project"
codex_home = Path(os.getenv("HARNESS_STATE_DIR", "tmp/harnesses/codex")) / "home"
personal_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
prompt = "Shipping costs 8 dollars below 100 dollars and is free at or above 100 dollars. What is the shipping fee for an order of exactly 100 dollars? Answer in one sentence. Do not use tools."

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent = CodexAgent(
    id="codex-home",
    model=os.getenv("CODEX_MODEL", "gpt-5.6-luna"),
    cwd=str(workspace),
    codex_home=codex_home,
    sandbox="read-only",
    approval_mode="deny_all",
    reasoning_effort="low",
)


def threads(home: Path) -> set:
    return (
        set((home / "sessions").rglob("*.jsonl"))
        if (home / "sessions").is_dir()
        else set()
    )


# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key and not (codex_home / "auth.json").exists():
        agent.login_api_key(api_key)

    personal_before = threads(personal_home)
    scratch_before = threads(codex_home)

    agent.print_response(prompt, stream=True)

    leaked = threads(personal_home) - personal_before
    written = threads(codex_home) - scratch_before
    print(f"\nThreads written under {codex_home.resolve()}: {len(written)}")
    for path in sorted(written):
        print(f"  {path.relative_to(codex_home)}")
    if leaked:
        raise SystemExit(
            f"The run reached your personal history at {personal_home}: {sorted(leaked)}"
        )
    print(f"Your personal history at {personal_home} is unchanged.")
