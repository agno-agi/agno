"""
AG-UI Protocol Router for FastAPI

This module provides the FastAPI router implementation for AG-UI protocol endpoints.
"""
from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
from ag_ui.core import RunAgentInput
from ag_ui.encoder import EventEncoder

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
    
    if not agent:
        raise ValueError("An agent must be provided")
    
    @router.post("/awp")
    async def agent_with_protocol(request: Request):
        """
        AG-UI Agent With Protocol endpoint
        
        This endpoint accepts AG-UI protocol requests and returns streaming responses.
        """
        # Get agent name from query params if we have a router
        app = request.app
        agent_to_use = agent
        
        # Check if we have an agent router (for multi-agent support)
        if hasattr(app.state, 'agent_router'):
            agent_name = request.query_params.get("agent", "chat_agent")
            agent_to_use = app.state.agent_router.get_agent(agent_name)
        elif hasattr(app, 'agent_router'):
            agent_name = request.query_params.get("agent", "chat_agent")
            agent_to_use = app.agent_router.get_agent(agent_name)
        
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
                        yield encoded.encode('utf-8')
            except Exception as e:
                # Send error event
                error_event = bridge.create_error_event(str(e))
                encoded = encoder.encode(error_event)
                if encoded:
                    yield encoded.encode('utf-8')
        
        # Return streaming response
        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            }
        )
    
    @router.get("/health")
    async def health_check():
        """Health check endpoint"""
        return {"status": "healthy", "protocol": "ag-ui"}
    
    return router 