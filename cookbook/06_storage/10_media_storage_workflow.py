"""
Workflow Media Storage (S3)
===========================

Demonstrates media offload across a workflow. A workflow persists media from two places,
and both are offloaded to S3 with only a MediaReference kept in the database:

- media attached to workflow.run(images=...)
- media a step's agent produced

Step inputs are rehydrated before each step runs, so a step downstream of an offloaded
one receives the bytes rather than an empty pointer.

Requirements:
- uv pip install 'agno[s3]'
- AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION
- Set MEDIA_S3_BUCKET to a bucket you own
"""

import os

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media import Image
from agno.media.storage import S3MediaStorage
from agno.models.openai import OpenAIResponses
from agno.workflow import Step, Workflow

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
IMAGE_URL = "https://thumbs.dreamstime.com/b/mountain-landscape-pieniny-national-park-foot-tatra-mountains-mountain-landscape-pieniny-national-park-437239881.jpg?w=768"

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
    prefix="agno/workflow-media/",
    presigned_url_expiry=3600,
)

# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

describer = Agent(
    name="Describer",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=["Describe the attached image in two sentences."],
)

summarizer = Agent(
    name="Summarizer",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=["Rewrite the description you are given as a single short caption."],
)

# The second step runs after the first has been persisted, so its step input is
# rehydrated from storage before the model sees it.
workflow = Workflow(
    name="Image Description Workflow",
    db=SqliteDb(db_file="tmp/workflow_media.db"),
    media_storage=storage,
    store_media=True,
    steps=[
        Step(name="describe", agent=describer),
        Step(name="summarize", agent=summarizer),
    ],
)

# ---------------------------------------------------------------------------
# Run the Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Download the image so the workflow sends bytes. URL-only media is skipped during
    # offload unless the backend is built with persist_remote_urls=True.
    image_bytes = httpx.get(IMAGE_URL, follow_redirects=True).content

    session_id = "workflow-media-session"
    response = workflow.run(
        input="Describe this image, then caption it.",
        images=[Image(content=image_bytes, format="jpeg", mime_type="image/jpeg")],
        session_id=session_id,
    )
    print(response.content)

    # What landed in the database: a pointer, not the bytes. A workflow keeps its media on
    # run.images and on each step result, not under run.input the way an agent run does.
    session = workflow.get_session(session_id=session_id)
    for run in session.runs or []:
        media = list(run.images or [])
        for step_result in run.step_results or []:
            for step_output in (
                step_result if isinstance(step_result, list) else [step_result]
            ):
                media.extend(step_output.images or [])

        for image in media:
            reference = image.media_reference
            if reference is None:
                print("\nImage was NOT offloaded (kept inline)")
                continue
            print("\nOffloaded to object storage")
            print(f"  storage key : {reference.storage_key}")
            print(f"  bucket      : {reference.bucket}")
            print(f"  size        : {reference.size} bytes")
            print(f"  inline bytes: {image.content}")
