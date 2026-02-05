from typing import List, Optional, Union

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

from agno.agent import Agent, RemoteAgent
from agno.media import File, Image
from agno.os.interfaces.slack.security import verify_slack_signature
from agno.team import RemoteTeam, Team
from agno.tools.slack import SlackTools
from agno.utils.log import log_error
from agno.workflow import RemoteWorkflow, Workflow


class SlackEventResponse(BaseModel):
    """Response model for Slack event processing"""

    status: str = Field(default="ok", description="Processing status")


class SlackChallengeResponse(BaseModel):
    """Response model for Slack URL verification challenge"""

    challenge: str = Field(description="Challenge string to echo back to Slack")


def attach_routes(
    router: APIRouter,
    agent: Optional[Union[Agent, RemoteAgent]] = None,
    team: Optional[Union[Team, RemoteTeam]] = None,
    workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
    reply_to_mentions_only: bool = True,
) -> APIRouter:
    # Determine entity type for documentation
    entity_type = "agent" if agent else "team" if team else "workflow" if workflow else "unknown"

    @router.post(
        "/events",
        operation_id=f"slack_events_{entity_type}",
        name="slack_events",
        description="Process incoming Slack events",
        response_model=Union[SlackChallengeResponse, SlackEventResponse],
        response_model_exclude_none=True,
        responses={
            200: {"description": "Event processed successfully"},
            400: {"description": "Missing Slack headers"},
            403: {"description": "Invalid Slack signature"},
        },
    )
    async def slack_events(request: Request, background_tasks: BackgroundTasks):
        body = await request.body()
        timestamp = request.headers.get("X-Slack-Request-Timestamp")
        slack_signature = request.headers.get("X-Slack-Signature", "")

        if not timestamp or not slack_signature:
            raise HTTPException(status_code=400, detail="Missing Slack headers")

        if not verify_slack_signature(body, timestamp, slack_signature):
            raise HTTPException(status_code=403, detail="Invalid signature")

        data = await request.json()

        # Handle URL verification
        if data.get("type") == "url_verification":
            return SlackChallengeResponse(challenge=data.get("challenge"))

        # Process other event types (e.g., message events) asynchronously
        if "event" in data:
            event = data["event"]
            if event.get("bot_id"):
                pass
            else:
                background_tasks.add_task(_process_slack_event, event)

        return SlackEventResponse(status="ok")

    async def _process_slack_event(event: dict):
        event_type = event.get("type")

        # Only handle app_mention and message events
        if event_type not in ("app_mention", "message"):
            return

        channel_type = event.get("channel_type", "")

        # Handle duplicate replies
        if not reply_to_mentions_only and event_type == "app_mention":
            return

        # If reply_to_mentions_only is True, ignore every message that is not a DM
        if reply_to_mentions_only and event_type == "message" and channel_type != "im":
            return

        # Extract event data
        user = None
        message_text = event.get("text", "")
        channel_id = event.get("channel", "")
        user = event.get("user")
        if event.get("thread_ts"):
            ts = event.get("thread_ts", "")
        else:
            ts = event.get("ts", "")

        # Use the timestamp as the session id, so that each thread is a separate session
        session_id = ts

        files, images = _download_event_files(event)

        if agent:
            response = await agent.arun(
                message_text,
                user_id=user,
                session_id=session_id,
                files=files if files else None,
                images=images if images else None,
            )
        elif team:
            response = await team.arun(message_text, user_id=user, session_id=session_id)  # type: ignore
        elif workflow:
            response = await workflow.arun(message_text, user_id=user, session_id=session_id)  # type: ignore

        if response:
            if response.status == "ERROR":
                log_error(f"Error processing message: {response.content}")
                _send_slack_message(
                    channel=channel_id,
                    message="Sorry, there was an error processing your message. Please try again later.",
                    thread_ts=ts,
                )
                return

            if hasattr(response, "reasoning_content") and response.reasoning_content:
                _send_slack_message(
                    channel=channel_id,
                    message=f"Reasoning: \n{response.reasoning_content}",
                    thread_ts=ts,
                    italics=True,
                )

            _send_slack_message(channel=channel_id, message=response.content or "", thread_ts=ts)

            _upload_response_media(response, channel_id, ts)

    def _download_event_files(event: dict) -> tuple[List[File], List[Image]]:
        files: List[File] = []
        images: List[Image] = []

        if not event.get("files"):
            return files, images

        slack_tools = SlackTools()
        for file_info in event["files"]:
            file_id = file_info.get("id")
            filename = file_info.get("name", "file")
            mimetype = file_info.get("mimetype", "application/octet-stream")

            try:
                file_content = slack_tools.download_file_bytes(file_id)
                if file_content is not None:
                    if mimetype.startswith("image/"):
                        images.append(Image(content=file_content, id=file_id))
                    else:
                        safe_mime = mimetype if mimetype in File.valid_mime_types() else None
                        files.append(File(content=file_content, filename=filename, mime_type=safe_mime))
            except Exception as e:
                log_error(f"Failed to download file {file_id}: {e}")

        return files, images

    def _upload_response_media(response, channel_id: str, thread_ts: str):
        slack_tools = SlackTools()

        if hasattr(response, "images") and response.images:
            for image in response.images:
                if image.content:
                    try:
                        slack_tools.upload_file(
                            channel=channel_id,
                            content=image.content,
                            filename=getattr(image, "filename", None) or "image.png",
                            thread_ts=thread_ts,
                        )
                    except Exception as e:
                        log_error(f"Failed to upload image: {e}")

        if hasattr(response, "files") and response.files:
            for file in response.files:
                if file.content:
                    try:
                        slack_tools.upload_file(
                            channel=channel_id,
                            content=file.content,
                            filename=getattr(file, "filename", None) or "file",
                            thread_ts=thread_ts,
                        )
                    except Exception as e:
                        log_error(f"Failed to upload file: {e}")

        if hasattr(response, "videos") and response.videos:
            for video in response.videos:
                if video.content:
                    try:
                        slack_tools.upload_file(
                            channel=channel_id,
                            content=video.content,
                            filename=getattr(video, "filename", None) or "video.mp4",
                            thread_ts=thread_ts,
                        )
                    except Exception as e:
                        log_error(f"Failed to upload video: {e}")

        if hasattr(response, "audio") and response.audio:
            for audio in response.audio:
                if audio.content:
                    try:
                        slack_tools.upload_file(
                            channel=channel_id,
                            content=audio.content,
                            filename=getattr(audio, "filename", None) or "audio.mp3",
                            thread_ts=thread_ts,
                        )
                    except Exception as e:
                        log_error(f"Failed to upload audio: {e}")

    def _send_slack_message(channel: str, thread_ts: str, message: str, italics: bool = False):
        if len(message) <= 40000:
            if italics:
                # Handle multi-line messages by making each line italic
                formatted_message = "\n".join([f"_{line}_" for line in message.split("\n")])
                SlackTools().send_message(channel=channel, text=formatted_message or "", thread_ts=thread_ts)
            else:
                SlackTools().send_message(channel=channel, text=message or "", thread_ts=thread_ts)
            return

        message_batches = [message[i : i + 40000] for i in range(0, len(message), 40000)]
        for i, batch in enumerate(message_batches, 1):
            batch_message = f"[{i}/{len(message_batches)}] {batch}"
            if italics:
                # Handle multi-line messages by making each line italic
                formatted_batch = "\n".join([f"_{line}_" for line in batch_message.split("\n")])
                SlackTools().send_message(channel=channel, text=formatted_batch or "", thread_ts=thread_ts)
            else:
                SlackTools().send_message(channel=channel, text=batch_message or "", thread_ts=thread_ts)

    return router
