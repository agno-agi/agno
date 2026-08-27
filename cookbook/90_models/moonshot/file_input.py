"""
Moonshot File Input
===================

Kimi does not accept inline file attachments. Instead each file is uploaded to Kimi's
Files endpoint with purpose="file-extract", its text is extracted server-side, and that
text is injected into the message - all handled automatically by the MoonShot model.

Files are uploaded once - the Moonshot file id is stored on the File object - so
add_history_to_context does not re-upload the same file on later turns.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media import File
from agno.models.moonshot import MoonShot

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=MoonShot(id="kimi-k3", reasoning_effort="low"),
    db=SqliteDb(db_file="tmp/moonshot_file_input.db"),
    markdown=True,
    add_history_to_context=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response(
        "Summarize the contents of the attached file.",
        files=[
            File(url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf")
        ],
    )
    # The file is not re-uploaded here - its stored file id is reused.
    agent.print_response("Suggest me a recipe from the attached file.")
