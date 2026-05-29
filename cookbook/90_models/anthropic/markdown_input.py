"""
Anthropic Markdown Input
========================

Demonstrates passing markdown files to Claude using the correct
text/markdown MIME type.
"""

from pathlib import Path
from textwrap import dedent

from agno.agent import Agent
from agno.media import File
from agno.models.anthropic import Claude

# ---------------------------------------------------------------------------
# Create a sample markdown file
# ---------------------------------------------------------------------------

md_path = Path(__file__).parent.joinpath("sample_notes.md")
md_path.write_text(
    dedent("""\
    # Project Status

    ## Completed
    - User authentication module
    - Database schema design
    - API rate limiting

    ## In Progress
    - Payment integration (70% done)
    - Email notification system (30% done)

    ## Blocked
    - Mobile app deployment - waiting on App Store review
    - Analytics dashboard - depends on payment integration
    """)
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Claude(id="claude-sonnet-4-20250514"),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Summarize the project status and identify the critical path to completion.",
        files=[
            File(
                filepath=md_path,
                mime_type="text/markdown",
            ),
        ],
    )
