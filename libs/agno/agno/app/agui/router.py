"""
AG-UI Protocol Router for FastAPI

This module provides the FastAPI router implementation for AG-UI protocol endpoints.
"""

from typing import Optional

from ag_ui.core import RunAgentInput
from ag_ui.encoder import EventEncoder
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from agno.agent.agent import Agent
from agno.team.team import Team

from .bridge import AGUIBridge


def get_agui_router(agent: Optional[Agent] = None, team: Optional[Team] = None) -> APIRouter:
    """
    Create an AG-UI compatible router for Agno agents.

    Args:
        agent: The Agno agent to expose via AG-UI protocol
        team: The Agno team to expose via AG-UI protocol (not implemented yet)

    Returns:
        FastAPI APIRouter configured for AG-UI protocol
    """
    router = APIRouter()

    if team:
        raise NotImplementedError("Team support is not yet implemented")

    @router.post("/awp")
    async def agent_with_protocol(request: Request):
        """
        AG-UI Agent With Protocol endpoint

        This endpoint accepts AG-UI protocol requests and returns streaming responses.
        """
        # Get the agent from the app router
        app = request.app
        agent_to_use = agent

        # Check if we have an agent router stored in the app
        if hasattr(app, "_agui_router"):
            agent_to_use = app._agui_router.get_agent(request)
        elif agent_to_use is None:
            raise HTTPException(status_code=500, detail="No agent configured")

        if not agent_to_use:
            # Check if the requested agent name is compatible
            agent_name = request.query_params.get("agent", "chat_agent")
            if agent_name in ["chat_agent", "agenticChatAgent"] and agent:
                agent_to_use = agent
            else:
                raise HTTPException(status_code=404, detail="Agent not found")

        # Parse the request body
        try:
            body = await request.json()
            run_input = RunAgentInput(**body)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid request: {str(e)}")

        # Create the bridge
        bridge = AGUIBridge(agent=agent_to_use)

        # Create event encoder
        encoder = EventEncoder()

        async def event_generator():
            """Generate AG-UI events from the agent response"""
            try:
                async for event in bridge.run_agent(run_input):
                    # Encode the event
                    encoded = encoder.encode(event)
                    if encoded:
                        yield encoded.encode("utf-8")
            except Exception as e:
                # Send error event
                error_event = bridge.create_error_event(str(e))
                encoded = encoder.encode(error_event)
                if encoded:
                    yield encoded.encode("utf-8")

        # Return streaming response
        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            },
        )

    @router.get("/health")
    async def health_check():
        """Health check endpoint"""
        return {"status": "healthy", "protocol": "ag-ui"}

    @router.get("/agents")
    async def list_agents(request: Request):
        """List available agents"""
        app = request.app
        if hasattr(app, "_agui_router"):
            return app._agui_router.list_agents()
        else:
            # Support both agent names for compatibility
            return {
                "agents": ["chat_agent", "agenticChatAgent"],
                "endpoints": {
                    "chat_agent": "/agui/awp?agent=chat_agent",
                    "agenticChatAgent": "/agui/awp?agent=agenticChatAgent",
                },
            }

    return router
