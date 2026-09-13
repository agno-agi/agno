"""
Unpack uploaded .zip files before the model call
================================================

AgentOS accepts a ``.zip`` upload, but no model provider opens one: the archive
is forwarded as the same compressed bytes that left the browser, so the model
sees a blob rather than the files inside it.

A ``pre_hook`` runs after the upload is received and before the model is called,
and it is handed ``run_input.files``. Replacing that list with the archive's
contents is what the model then receives, so an agent can answer from a zip
without AgentOS ever having to unpack one itself.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/04_run_lifecycle/unpack_archives.py
Try: Upload any .zip to the Unpack Agent from the AgentOS UI and ask what is inside it
"""

import io
import mimetypes
import zipfile

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media import File
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.run.agent import RunInput

# ---------------------------------------------------------------------------
# Create Unpacking AgentOS
# ---------------------------------------------------------------------------


def unpack_archives(run_input: RunInput) -> None:
    """Replace every uploaded .zip with the files it contains."""
    if not run_input.files:
        return

    unpacked: list[File] = []
    for uploaded in run_input.files:
        if uploaded.mime_type != "application/zip" or not uploaded.content:
            unpacked.append(uploaded)
            continue

        with zipfile.ZipFile(io.BytesIO(uploaded.content)) as archive:
            for entry in archive.infolist():
                # Archives written by macOS Finder carry a hidden "__MACOSX/._<name>"
                # entry per file holding Finder metadata rather than content.
                if entry.is_dir() or entry.filename.startswith("__MACOSX/"):
                    continue
                name = entry.filename.rsplit("/", 1)[-1]
                if name.startswith("._"):
                    continue

                # File validates mime_type, so resolve it per entry and fall back to
                # None for anything outside File.valid_mime_types().
                mime_type, _ = mimetypes.guess_type(name)
                if mime_type not in File.valid_mime_types():
                    mime_type = None

                unpacked.append(
                    File(
                        content=archive.read(entry),
                        filename=name,
                        format=name.rsplit(".", 1)[-1].lower(),
                        mime_type=mime_type,
                    )
                )

    run_input.files = unpacked


db = SqliteDb(
    id="unpack-db",
    db_file="tmp/agent_os_unpack.db",
)

unpack_agent = Agent(
    id="unpack-agent",
    name="Unpack Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    pre_hooks=[unpack_archives],
    instructions="Answer only from the attached files and quote the exact values you read.",
)

agent_os = AgentOS(
    id="unpack-os",
    db=db,
    agents=[unpack_agent],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Unpacking AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app, port=7777)
