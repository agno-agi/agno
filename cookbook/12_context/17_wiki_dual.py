"""
Wiki Context Provider (dual: company knowledge + company voice)
================================================================

Two `WikiContextProvider` instances on one agent — same provider type,
two storage strategies, two scopes:

- `company_knowledge` — full read + write surface backed by a git
  repo. The agent answers product / customer questions from it and
  files new pages back when it learns something.
- `company_voice` — read-only (`write=False`) surface backed by the
  filesystem (shipped in the container). Voice rules are
  code-managed: changes go through PRs, not agent edits.

The outer agent sees four tools: `query_company_knowledge`,
`update_company_knowledge`, and `query_company_voice` only — no
`update_company_voice` because the provider was instantiated with
`write=False`.

Requires: OPENAI_API_KEY
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from agno.agent import Agent
from agno.context.wiki import FileSystemBackend, WikiContextProvider
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Seed both wikis on the local filesystem (production: knowledge would be
# a GitBackend, voice would ship in the container)
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent / "demo-wiki-dual"
KNOWLEDGE_PATH = ROOT / "knowledge"
VOICE_PATH = ROOT / "voice"
if ROOT.exists():
    shutil.rmtree(ROOT)
KNOWLEDGE_PATH.mkdir(parents=True)
VOICE_PATH.mkdir(parents=True)

(KNOWLEDGE_PATH / "README.md").write_text(
    "# Company Knowledge\n\nProduct facts, customer info, runbooks.\n"
)
(VOICE_PATH / "x.md").write_text(
    "# X (Twitter) Voice\n\n"
    "- Lowercase first word, no emojis.\n"
    "- Lead with the punchline, then 1-2 lines of context.\n"
    "- 280 char hard cap. No threads unless asked.\n"
)
(VOICE_PATH / "linkedin.md").write_text(
    "# LinkedIn Voice\n\n"
    "- First line is the hook; second line is the proof; third is the takeaway.\n"
    "- Plain prose, no marketing words ('leverage', 'unlock', 'game-changing').\n"
    "- One concrete example per post.\n"
)

# ---------------------------------------------------------------------------
# Two providers, two roles
# ---------------------------------------------------------------------------
knowledge = WikiContextProvider(
    id="company_knowledge",
    backend=FileSystemBackend(path=KNOWLEDGE_PATH),
    model=OpenAIResponses(id="gpt-5.4-mini"),
)
voice = WikiContextProvider(
    id="company_voice",
    backend=FileSystemBackend(path=VOICE_PATH),
    write=False,  # voice is code-managed; agent reads, doesn't edit
    model=OpenAIResponses(id="gpt-5.4-mini"),
)

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=knowledge.get_tools() + voice.get_tools(),
    instructions=(
        knowledge.instructions()
        + "\n\n"
        + voice.instructions()
        + "\n\nWhen drafting external content, consult company_voice first."
    ),
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
async def _run() -> None:
    print("\nProvider tool surface:")
    for t in agent.tools or []:
        print(f"  - {getattr(t, 'name', t)}")

    prompt = (
        "Draft a short LinkedIn post announcing that we shipped a "
        "wiki context provider this week. Consult the voice rules first."
    )
    print(f"\n> {prompt}\n")
    await agent.aprint_response(prompt)

    # Write surface check: no update_company_voice tool exists.
    assert not any(
        getattr(t, "name", "") == "update_company_voice" for t in (agent.tools or [])
    ), "voice provider should not expose an update tool when write=False"
    print("\n[ok] voice exposes only query_company_voice — no update tool")


if __name__ == "__main__":
    asyncio.run(_run())
