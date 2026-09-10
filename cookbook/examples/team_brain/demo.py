"""Two local demo identities contribute to one shared project.
Direct Python calls are trusted local inputs, not authentication proof.
"""

import asyncio
import sys

from team_brain import DECISION_LOG, fs, recall, remember


# ---------------------------------------------------------------------------
# Create the demo: shared decisions with independent authors
# ---------------------------------------------------------------------------
async def main() -> None:
    if "--recall-only" not in sys.argv:
        print(
            await remember(
                "Onboarding",
                "Use a checklist",
                "It is easier to keep up to date",
                "alice",
            )
        )
        print(
            await remember(
                "Onboarding",
                "Test with a new user by Friday",
                "Find setup gaps before publishing",
                "bob",
            )
        )
    print(
        await recall(
            "What did we decide for Onboarding, why, and who decided?", "alice"
        )
    )
    print(fs.read(DECISION_LOG))


# ---------------------------------------------------------------------------
# Run the same tools and librarian used by MCP
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    asyncio.run(main())
