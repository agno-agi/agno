"""
ClaudeAgent: Own Config Directory
=================================
Run Claude Code under a scratch CLAUDE_CONFIG_DIR so the run stays out of your
personal Claude history.

By default the harness writes every conversation to ~/.claude, the same place
your interactive sessions go. config_dir points this agent at its own home.
The script snapshots your personal transcript list before the run and fails if
that list changed.

The scratch home needs its own login. Either export ANTHROPIC_API_KEY, which
the subprocess inherits, or log in once:

    CLAUDE_CONFIG_DIR=tmp/harnesses/claude/home claude login

See README.md for setup.
"""

import os
from pathlib import Path

from agno.agents.claude import ClaudeAgent

# ---------------------------------------------------------------------------
# Configure the Example
# ---------------------------------------------------------------------------
workspace = Path(__file__).resolve().parents[1] / "sample_project"
config_dir = Path(os.getenv("HARNESS_STATE_DIR", "tmp/harnesses/claude")) / "home"
personal_home = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
prompt = "Shipping costs 8 dollars below 100 dollars and is free at or above 100 dollars. What is the shipping fee for an order of exactly 100 dollars? Answer in one sentence. Do not use tools."

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent = ClaudeAgent(
    id="claude-config-dir",
    model="claude-sonnet-5-5",
    cwd=str(workspace),
    config_dir=config_dir,
    tools=[],
    setting_sources=[],
    strict_mcp_config=True,
)


def transcripts(home: Path) -> set:
    return (
        set((home / "projects").rglob("*.jsonl"))
        if (home / "projects").is_dir()
        else set()
    )


# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    personal_before = transcripts(personal_home)
    scratch_before = transcripts(config_dir)

    agent.print_response(prompt, stream=True)

    leaked = transcripts(personal_home) - personal_before
    written = transcripts(config_dir) - scratch_before
    print(f"\nTranscripts written under {config_dir.resolve()}: {len(written)}")
    for path in sorted(written):
        print(f"  {path.relative_to(config_dir)}")
    if leaked:
        raise SystemExit(
            f"The run reached your personal history at {personal_home}: {sorted(leaked)}"
        )
    print(f"Your personal history at {personal_home} is unchanged.")
