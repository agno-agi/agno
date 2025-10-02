from uuid import uuid4

from fastapi import HTTPException
from typing_extensions import List

try:
    from a2a.types import (
        Artifact,
        DataPart,
        FilePart,
        FileWithBytes,
        FileWithUri,
        Part,
        Role,
        SendMessageRequest,
        Task,
        TaskState,
        TaskStatus,
        TextPart,
    )
    from a2a.types import Message as A2AMessage
except ImportError as e:
    raise ImportError("`a2a` not installed. Please install it with `pip install -U a2a`") from e


from agno.media import Audio, File, Image, Video
from agno.run.agent import RunInput, RunOutput


async def map_a2a_request_to_run_input(request_body: dict) -> RunInput:
    """Map A2A SendMessageRequest to Agno RunInput.

    1. Validate the request
    2. Process message parts
    3. Build and return RunInput

    Args:
        request_body: A2A-valid JSON-RPC request body dict:

        ```json
        {
            "jsonrpc": "2.0",
            "method": "message/send",
            "id": "id",
            "params": {
                "message": {
                    "messageId": "id",
                    "role": "user",
                    "contextId": "id",
                    "parts": [{"kind": "text", "text": "Hello"}]
                }
            }
        }
        ```

    Returns:
        RunInput: The Agno RunInput
    """

    # 1. Validate the request
    try:
        a2a_request = SendMessageRequest.model_validate(request_body)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid A2A request: {str(e)}")

    a2a_message = a2a_request.params.message
    if a2a_message.role != "user":
        raise HTTPException(status_code=400, detail="Only user messages are accepted")

    # 2. Process message parts
    text_parts = []
    images = []
    videos = []
    audios = []
    files = []

    for part in a2a_message.parts:
        # Handle message text content
        if isinstance(part.root, TextPart):
            text_parts.append(part.root.text)

        # Handle message files
        elif isinstance(part.root, FilePart):
            file_data = part.root.file
            if isinstance(file_data, FileWithUri):
                if not file_data.mime_type:
                    continue
                elif file_data.mime_type.startswith("image/"):
                    images.append(Image(url=file_data.uri))
                elif file_data.mime_type.startswith("video/"):
                    videos.append(Video(url=file_data.uri))
                elif file_data.mime_type.startswith("audio/"):
                    audios.append(Audio(url=file_data.uri))
                else:
                    files.append(File(url=file_data.uri, mime_type=file_data.mime_type))
            elif isinstance(file_data, FileWithBytes):
                if not file_data.mime_type:
                    continue
                files.append(File(content=file_data.bytes, mime_type=file_data.mime_type))

        # Handle message structured data parts
        elif isinstance(part.root, DataPart):
            import json

            text_parts.append(json.dumps(part.root.data))

    # 3. Build and return RunInput
    complete_input_content = "\n".join(text_parts) if text_parts else ""
    return RunInput(
        input_content=complete_input_content,
        images=images if images else None,
        videos=videos if videos else None,
        audios=audios if audios else None,
        files=files if files else None,
    )


def map_run_output_to_a2a_task(run_output: RunOutput) -> Task:
    """Map the given RunOutput into an A2A Task.

    1. Handle output content
    2. Handle output media
    3. Build the A2A message
    4. Build and return the A2A task

    Args:
        run_output: The Agno RunOutput

    Returns:
        Task: The A2A Task
    """
    parts: List[Part] = []

    # 1. Handle output content
    if run_output.content:
        parts.append(Part(root=TextPart(text=run_output.content)))

    # 2. Handle output media
    artifacts: List[Artifact] = []
    if run_output.images:
        for idx, img in enumerate(run_output.images):
            artifact_parts = []
            if img.url:
                artifact_parts.append(Part(root=FilePart(file=FileWithUri(uri=img.url, mime_type="image/jpeg"))))
            artifacts.append(
                Artifact(
                    artifact_id=str(uuid4()),
                    name=f"image_{idx}",
                    description=f"Generated image {idx}",
                    parts=artifact_parts,
                )
            )
    if run_output.videos:
        for idx, vid in enumerate(run_output.videos):
            artifact_parts = []
            if vid.url:
                artifact_parts.append(Part(root=FilePart(file=FileWithUri(uri=vid.url, mime_type="video/mp4"))))
            artifacts.append(
                Artifact(
                    artifact_id=str(uuid4()),
                    name=f"video_{idx}",
                    description=f"Generated video {idx}",
                    parts=artifact_parts,
                )
            )
    if run_output.audio:
        for idx, aud in enumerate(run_output.audio):
            artifact_parts = []
            if aud.url:
                artifact_parts.append(Part(root=FilePart(file=FileWithUri(uri=aud.url, mime_type="audio/mpeg"))))
            artifacts.append(
                Artifact(
                    artifact_id=str(uuid4()),
                    name=f"audio_{idx}",
                    description=f"Generated audio {idx}",
                    parts=artifact_parts,
                )
            )
    if run_output.files:
        for idx, file in enumerate(run_output.files):
            artifact_parts = []
            if file.url:
                artifact_parts.append(
                    Part(
                        root=FilePart(
                            file=FileWithUri(uri=file.url, mime_type=file.mime_type or "application/octet-stream")
                        )
                    )
                )
            artifacts.append(
                Artifact(
                    artifact_id=str(uuid4()),
                    name=getattr(file, "name", f"file_{idx}"),
                    description=f"Generated file {idx}",
                    parts=artifact_parts,
                )
            )

    # 3. Build the A2A message
    agent_message = A2AMessage(
        message_id=str(uuid4()),
        role=Role.agent,
        parts=parts,
        context_id=run_output.session_id,
        task_id=run_output.run_id,
    )

    # 4. Build and return the A2A task
    return Task(
        id=run_output.run_id or str(uuid4()),
        context_id=run_output.session_id or str(uuid4()),
        status=TaskStatus(state=TaskState.completed),
        history=[agent_message],
        artifacts=artifacts if artifacts else None,
    )
