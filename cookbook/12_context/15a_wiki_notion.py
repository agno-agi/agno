"""
Wiki Context Provider (Notion database backend)
===============================================

Same ``WikiContextProvider`` surface as the filesystem and git wikis,
but the wiki is backed by a Notion database. Each row in the database
is mirrored as one ``.md`` file under ``local_path``. Frontmatter
records the Notion page id and last-edited timestamp:

    ---
    notion_page_id: 8a7c2f3e-...
    notion_last_edited: 2026-05-13T10:22:00Z
    title: Acme Corp
    ---

    # Acme Corp
    ...

Notion is the source of truth. Pages are flat (one row per page, no
nesting); the nested-tree mode (``NotionPageBackend``) is on the
roadmap. ``sync()`` wipes the local ``*.md`` mirror and rebuilds from
the database; ``commit_after_write`` pushes block updates, creates
pages for new files, and archives pages whose files were deleted
locally. If a page was edited inside Notion between sync and commit,
the commit raises rather than overwrite — call ``wiki.sync()`` and
retry.

This demo files a customer call summary into a Notion database and
reads it back. The point: the same database is the one your AEs open
in Notion. The agent files structured notes (markdown locally, blocks
in Notion); humans read and edit them in the UI they already use.

Auth is an integration token. Create one at
https://www.notion.so/profile/integrations and invite it to your
database via the database's "Connections" menu.

Requires:
    OPENAI_API_KEY
    NOTION_API_KEY        (integration token, starts with ``ntn_`` or ``secret_``)
    NOTION_DATABASE_ID    (UUID from the database URL)

    Optional:
    WIKI_LOCAL_PATH       (default: ./demo-wiki-notion/ next to this cookbook;
                           override to mirror elsewhere)
"""

import asyncio
import os
import sys
from pathlib import Path

from agno.agent import Agent
from agno.context.wiki import NotionDatabaseBackend, WikiContextProvider
from agno.context.wiki.notion_ops import parse_page_file
from agno.models.openai import OpenAIResponses

TOKEN = os.getenv("NOTION_API_KEY")
DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
LOCAL_PATH = os.getenv("WIKI_LOCAL_PATH") or str(
    Path(__file__).resolve().parent / "demo-wiki-notion"
)

if not TOKEN or not DATABASE_ID:
    print(
        "Skipping Notion wiki demo - set NOTION_API_KEY and NOTION_DATABASE_ID to run.\n"
        "Example:\n"
        "  NOTION_API_KEY=ntn_xxx \\\n"
        "  NOTION_DATABASE_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx \\\n"
        "  .venvs/demo/bin/python cookbook/12_context/15a_wiki_notion.py"
    )
    sys.exit(0)

# ---------------------------------------------------------------------------
# Create the provider
# ---------------------------------------------------------------------------
backend = NotionDatabaseBackend(
    database_id=DATABASE_ID,
    token=TOKEN,
    local_path=LOCAL_PATH,
)
wiki = WikiContextProvider(
    id="wiki",
    backend=backend,
    model=OpenAIResponses(id="gpt-5.4-mini"),
)

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=wiki.get_tools(),
    instructions=wiki.instructions(),
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
async def _run() -> None:
    await wiki.asetup()
    print(f"\nwiki.status() = {wiki.status()}\n")

    # The Notion DB is flat (one row per page), so the file must land at
    # the mirror root. The agent names the file; we just nudge it toward
    # a clean slug so the auto-derived Notion page title reads well.
    write_prompt = (
        "File a call summary for Acme Corp as acme-corp.md at the wiki root. "
        "Sections: Attendees, Pain Points, Next Steps. "
        "They're evaluating us against Competitor X and need SSO by Q3. "
        "Keep it under twenty lines."
    )
    print(f"> {write_prompt}\n")
    await agent.aprint_response(write_prompt)

    print()
    read_prompt = (
        "What's the status with Acme Corp? When's their SSO deadline? Cite the page."
    )
    print(f"> {read_prompt}\n")
    await agent.aprint_response(read_prompt)

    # ---------------------------------------------------------------------
    # Round-trip proof: the local .md is real, and the Notion page is
    # clickable. Same content, two surfaces.
    # ---------------------------------------------------------------------
    pages = sorted(Path(LOCAL_PATH).glob("*.md"))
    assert pages, f"agent did not file any pages under {LOCAL_PATH}"
    print("\n[ok] wiki pages:")
    for path in pages:
        fm, _ = parse_page_file(path.read_text(encoding="utf-8"))
        size = path.stat().st_size
        rel = path.relative_to(Path(LOCAL_PATH))
        if fm.notion_page_id:
            page_url = f"https://www.notion.so/{fm.notion_page_id.replace('-', '')}"
            print(f"  - {rel} ({size} bytes)")
            print(f"    open in Notion: {page_url}")
        else:
            print(f"  - {rel} ({size} bytes) — no notion_page_id yet, commit pending")


if __name__ == "__main__":
    asyncio.run(_run())
