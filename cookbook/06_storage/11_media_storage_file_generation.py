"""
Generated File Storage (S3)
===========================

Demonstrates media offload for files the agent *generates*, rather than files you attach.

FileGenerationTools returns file bytes on the run, and media storage treats them exactly
like an attachment: the bytes go to S3 and the database row keeps only a MediaReference.
The generated filename and mime type travel onto the reference, so a reader knows what the
object is without downloading it.

Note save_files=False below. The tool can also write to a local directory, but that is a
separate copy on the machine that ran the agent — media storage is what makes a generated
file retrievable from anywhere.

Reading one back: pass the storage handle to get_content_bytes(storage=...) for the bytes,
or get_url(storage=...) for a freshly-signed link. Both have async variants.

Requirements:
- uv pip install 'agno[s3]'
- AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION
- Set MEDIA_S3_BUCKET to a bucket you own
"""

import os
from pathlib import Path

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media.storage import S3MediaStorage
from agno.models.openai import OpenAIResponses
from agno.tools.file_generation import FileGenerationTools

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

# A bucket you do not own makes every upload fail, and offload falls back to inline
# base64 — the run still succeeds, so the failure is easy to miss. Ask for the bucket
# up front instead.
bucket = os.getenv("MEDIA_S3_BUCKET")
if not bucket:
    raise ValueError("MEDIA_S3_BUCKET must be set to an S3 bucket you own")

storage = S3MediaStorage(
    bucket=bucket,
    region=os.getenv(
        "AWS_REGION"
    ),  # unset falls back to AWS_DEFAULT_REGION or ~/.aws/config
    prefix="agno/generated/",
    presigned_url_expiry=3600,
)

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    db=SqliteDb(db_file="tmp/generated_media.db"),
    media_storage=storage,
    store_media=True,
    # save_files=False keeps the bytes on the run, which is what media storage offloads.
    tools=[FileGenerationTools(all=True, save_files=False)],
    instructions=[
        "Use the appropriate file-generation tool when asked for an output file.",
        "Always use a descriptive filename with the correct extension.",
        "Briefly explain what you generated.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    session_id = "generated-media-session"

    response = agent.run(
        "Generate a CSV of the five largest planets with their diameter in km.",
        session_id=session_id,
    )
    print(response.content)

    # The generated file on the live run still carries its bytes — offload works on a
    # copy, so what run() hands back is never emptied.
    for file in response.files or []:
        size = len(file.content) if file.content else 0
        print(f"\nOn the returned run: {file.filename} ({size} bytes in memory)")

    # The database row holds a pointer instead.
    session = agent.get_session(session_id=session_id)
    for run in session.runs or []:
        for file in run.files or []:
            reference = file.media_reference
            if reference is None:
                print("\nFile was NOT offloaded (kept inline)")
                continue
            print("\nIn the database row")
            print(f"  filename    : {reference.filename}")
            print(f"  mime type   : {reference.mime_type}")
            print(f"  storage key : {reference.storage_key}")
            print(f"  size        : {reference.size} bytes")
            print(f"  inline bytes: {file.content}")

            # -------------------------------------------------------------
            # Reading an offloaded file back
            # -------------------------------------------------------------
            # Pass the storage handle and the media object resolves itself. Without it,
            # a row that carries only a reference has no bytes to return.
            data = file.get_content_bytes(storage=storage)
            print(f"  downloaded  : {len(data) if data else 0} bytes")
            if data:
                first_line = data.decode("utf-8", errors="replace").splitlines()[0]
                print(f"  first line  : {first_line}")

            # A link to hand to a browser, re-signed from storage_key. None means the
            # backend cannot sign (local storage, or GCS with application-default
            # credentials) — read the bytes instead.
            url = file.get_url(storage=storage)
            print(f"  signed url  : {url[:80] + '...' if url else 'not available'}")

            # Save it locally
            if data and reference.filename:
                output_path = Path("tmp") / reference.filename
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(data)
                print(f"  saved to    : {output_path}")
