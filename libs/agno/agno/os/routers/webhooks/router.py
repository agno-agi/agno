"""Webhook router — receive external webhooks and invoke agents.

Enables services like Parallel Monitor to trigger agents when events are detected.
The webhook payload is formatted as a message and passed to the agent.
"""

import json
from typing import TYPE_CHECKING, Optional, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request

from agno.os.auth import get_authentication_dependency
from agno.os.routers.webhooks.schema import WebhookPayload, WebhookResponse
from agno.os.schema import NotFoundResponse
from agno.os.settings import AgnoAPISettings
from agno.os.utils import resolve_agent
from agno.registry import Registry
from agno.run.agent import RunOutput
from agno.utils.log import log_error, log_info

if TYPE_CHECKING:
    from agno.os.app import AgentOS


def get_webhook_router(os: "AgentOS", settings: AgnoAPISettings, registry: Optional[Registry]) -> APIRouter:
    """Create the webhook router for receiving external service callbacks.

    Args:
        os: The AgentOS instance.
        settings: API settings.
        registry: Agent registry.

    Returns:
        APIRouter with webhook endpoints.
    """
    router = APIRouter(tags=["Webhooks"])
    auth_dependency = get_authentication_dependency(settings)

    @router.post(
        "/webhooks/{agent_id}",
        operation_id="trigger_agent_webhook",
        summary="Trigger Agent via Webhook",
        description=(
            "Receive a webhook from an external service and invoke the specified agent. "
            "The webhook payload is formatted as context and passed to the agent. "
            "The agent runs in the background and returns immediately with run metadata.\n\n"
            "**Use cases:**\n"
            "- Parallel Monitor event detection\n"
            "- GitHub webhook events\n"
            "- Stripe payment events\n"
            "- Any external service that sends webhooks"
        ),
        response_model=WebhookResponse,
        responses={
            200: {"description": "Agent run triggered successfully"},
            404: {"description": "Agent not found", "model": NotFoundResponse},
        },
    )
    async def trigger_agent_webhook(
        agent_id: str,
        request: Request,
        payload: WebhookPayload,
        session_id: str | None = None,
        user_id: str | None = None,
        _: bool = Depends(auth_dependency),
    ) -> WebhookResponse:
        """Receive webhook and invoke agent with payload as context."""
        log_info(f"Webhook received for agent {agent_id}: type={payload.type}")

        agent = await resolve_agent(
            agent_id,
            os.agents,
            os.db,
            registry,
            request=request,
            user_id=user_id,
            session_id=session_id,
        )

        if session_id is None:
            session_id = str(uuid4())

        message = _format_webhook_message(payload)

        try:
            run_response = cast(
                RunOutput,
                await agent.arun(  # type: ignore[misc]
                    input=message,
                    session_id=session_id,
                    user_id=user_id,
                    stream=False,
                    background=True,
                ),
            )

            return WebhookResponse(
                run_id=run_response.run_id,
                session_id=run_response.session_id or session_id,
                status=run_response.status.value if run_response.status else "PENDING",
                agent_id=agent_id,
            )
        except Exception as e:
            log_error(f"Error invoking agent {agent_id} from webhook: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    return router


def _format_webhook_message(payload: WebhookPayload) -> str:
    """Format webhook payload as a message for the agent."""
    parts = ["A webhook event was received:"]

    if payload.type:
        parts.append(f"Event type: {payload.type}")

    if payload.timestamp:
        parts.append(f"Timestamp: {payload.timestamp}")

    if payload.data:
        parts.append(f"Data: {json.dumps(payload.data, indent=2)}")

    if payload.metadata:
        parts.append(f"Metadata: {json.dumps(payload.metadata, indent=2)}")

    extra = payload.model_extra
    if extra:
        parts.append(f"Additional fields: {json.dumps(extra, indent=2)}")

    parts.append("\nPlease process this event according to your instructions.")

    return "\n\n".join(parts)
