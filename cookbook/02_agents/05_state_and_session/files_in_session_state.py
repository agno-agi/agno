"""
Files In Session State
=============================

Record uploaded file metadata into session_state when files are not sent to
the model. See issue #7306.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media import File
from agno.models.openai import OpenAIResponses

# Create an Agent that records uploaded files into session state
# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    # Initialize the session state with an empty uploaded files list (default session state for all sessions)
    session_state={"uploaded_files": []},
    db=SqliteDb(db_file="tmp/agents.db"),
    # Do not send the file to the model; only record its metadata in session state
    send_media_to_model=False,
    # Record uploaded file metadata (id, filename, mime_type) into session_state["uploaded_files"]
    add_files_to_session_state=True,
    add_session_state_to_context=True,
    # You can use variables from the session state in the instructions
    instructions="Files the user has uploaded so far: {uploaded_files}",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Example usage
    agent.print_response(
        "Acknowledge the spreadsheet I just uploaded and tell me its filename.",
        files=[
            File(
                url="https://agno-public.s3.amazonaws.com/demo_data/sample.csv",
                filename="sample.csv",
                mime_type="text/csv",
            )
        ],
    )
    print("Session state:", agent.get_session_state())
