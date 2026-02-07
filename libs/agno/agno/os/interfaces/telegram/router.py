from os import getenv
from typing import Optional, Union

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from agno.agent.agent import Agent
from agno.agent.remote import RemoteAgent
from agno.media import Image
from agno.team.remote import RemoteTeam
from agno.team.team import Team
from agno.utils.log import log_error, log_info, log_warning
from agno.workflow import RemoteWorkflow, Workflow

from .security import validate_webhook_secret_token


def attach_routes(
    router: APIRouter,
    agent: Optional[Union[Agent, RemoteAgent]] = None,
    team: Optional[Union[Team, RemoteTeam]] = None,
    workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
) -> APIRouter:
    if agent is None and team is None and workflow is None:
        raise ValueError("Either agent, team, or workflow must be provided.")

    bot_token = getenv("TELEGRAM_TOKEN")
    if not bot_token:
        raise ValueError("TELEGRAM_TOKEN environment variable is not set")

    base_url = f"https://api.telegram.org/bot{bot_token}"

    @router.get("/status")
    async def status():
        return {"status": "available"}

    @router.post("/webhook")
    async def webhook(request: Request, background_tasks: BackgroundTasks):
        try:
            # Validate secret token header
            secret_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
            if not validate_webhook_secret_token(secret_token):
                log_warning("Invalid webhook secret token")
                raise HTTPException(status_code=403, detail="Invalid secret token")

            body = await request.json()

            message = body.get("message")
            if not message:
                return {"status": "ignored"}

            background_tasks.add_task(process_message, message, agent, team, workflow)
            return {"status": "processing"}

        except HTTPException:
            raise
        except Exception as e:
            log_error(f"Error processing webhook: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def process_message(
        message: dict,
        agent: Optional[Union[Agent, RemoteAgent]],
        team: Optional[Union[Team, RemoteTeam]],
        workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
    ):
        chat_id = message.get("chat", {}).get("id")
        if not chat_id:
            log_warning("Received message without chat_id")
            return

        try:
            message_image = None

            # Send typing indicator
            await _send_chat_action(chat_id, "typing")

            if message.get("text"):
                message_text = message["text"]
            elif message.get("photo"):
                # Telegram sends multiple sizes; last is largest
                message_image = message["photo"][-1]["file_id"]
                message_text = message.get("caption", "Describe the image")
            else:
                return

            user_id = str(message.get("from", {}).get("id", chat_id))
            session_id = f"tg:{chat_id}"
            log_info(f"Processing message from {user_id}: {message_text}")

            images = None
            if message_image:
                image_bytes = await _download_file(message_image)
                if image_bytes:
                    images = [Image(content=image_bytes)]

            if agent:
                response = await agent.arun(
                    message_text,
                    user_id=user_id,
                    session_id=session_id,
                    images=images,
                )
            elif team:
                response = await team.arun(  # type: ignore
                    message_text,
                    user_id=user_id,
                    session_id=session_id,
                    images=images,
                )
            elif workflow:
                response = await workflow.arun(  # type: ignore
                    message_text,
                    user_id=user_id,
                    session_id=session_id,
                    images=images,
                )

            if response.status == "ERROR":
                await _send_message(
                    chat_id, "Sorry, there was an error processing your message. Please try again later."
                )
                log_error(response.content)
                return

            if response.reasoning_content:
                await _send_message(chat_id, f"Reasoning: \n{response.reasoning_content}")

            await _send_message(chat_id, response.content)  # type: ignore

        except Exception as e:
            log_error(f"Error processing message: {str(e)}")
            try:
                await _send_message(
                    chat_id, "Sorry, there was an error processing your message. Please try again later."
                )
            except Exception as send_error:
                log_error(f"Error sending error message: {str(send_error)}")

    async def _send_chat_action(chat_id: int, action: str) -> None:
        async with httpx.AsyncClient() as client:
            await client.post(f"{base_url}/sendChatAction", json={"chat_id": chat_id, "action": action})

    async def _download_file(file_id: str) -> Optional[bytes]:
        try:
            async with httpx.AsyncClient() as client:
                # Step 1: Get the file path
                resp = await client.get(f"{base_url}/getFile", params={"file_id": file_id})
                resp.raise_for_status()
                file_path = resp.json()["result"]["file_path"]

                # Step 2: Download the file
                file_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
                file_resp = await client.get(file_url)
                file_resp.raise_for_status()
                return file_resp.content
        except Exception as e:
            log_error(f"Error downloading file: {str(e)}")
            return None

    async def _send_message(chat_id: int, message: str) -> None:
        if len(message) <= 4096:
            async with httpx.AsyncClient() as client:
                await client.post(f"{base_url}/sendMessage", json={"chat_id": chat_id, "text": message})
            return

        # Split message into batches of 4000 characters (Telegram limit is 4096)
        message_batches = [message[i : i + 4000] for i in range(0, len(message), 4000)]
        async with httpx.AsyncClient() as client:
            for i, batch in enumerate(message_batches, 1):
                batch_message = f"[{i}/{len(message_batches)}] {batch}"
                await client.post(f"{base_url}/sendMessage", json={"chat_id": chat_id, "text": batch_message})

    return router
