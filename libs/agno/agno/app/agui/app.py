"""
AG-UI FastAPI Application

Main application that serves agents via the AG-UI protocol.
This app can route requests to different agents based on query parameters.
"""
from typing import Dict, Optional
from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.app.fastapi.app import FastAPIApp
from fastapi import Request

from .agents import (
    create_chat_agent,
    create_generative_ui_agent,
    create_human_in_loop_agent,
    create_predictive_state_agent,
    create_shared_state_agent,
    create_tool_ui_agent,
)

class AgentRouter:
    """Routes requests to different agents based on query parameters"""
    
    def __init__(self):
        # Create all agents
        self.agents = {
            "chat_agent": create_chat_agent(),
            "generative_ui_agent": create_generative_ui_agent(),
            "human_in_loop_agent": create_human_in_loop_agent(),
            "predictive_state_agent": create_predictive_state_agent(),
            "shared_state_agent": create_shared_state_agent(),
            "tool_ui_agent": create_tool_ui_agent(),
        }
        
        # Default agent for routing
        self.default_agent = self.agents["chat_agent"]
    
    def get_agent(self, agent_name: str) -> Optional[Agent]:
        """Get agent by name"""
        return self.agents.get(agent_name, self.default_agent)


def create_agui_app(
    name: str = "AG-UI Application",
    description: str = "Serves multiple agents via AG-UI protocol"
) -> FastAPIApp:
    """Create the AG-UI FastAPI application"""
    
    # Create router
    router = AgentRouter()
    
    # For now, we'll use the default agent as the main agent
    # The AG-UI router will handle the actual routing based on query params
    app = FastAPIApp(
        agent=router.default_agent,
        name=name,
        description=description
    )
    
    # Store the router for later use
    app.agent_router = router  # type: ignore
    
    # Create the FastAPI instance first
    api = app.get_app(enable_agui=True)
    
    # Add custom endpoint to list available agents
    @api.get("/agui/agents")
    def list_agents():
        """List all available agents and their endpoints"""
        return {
            "agents": list(router.agents.keys()),
            "endpoints": {
                name: f"/agui/awp?agent={name}"
                for name in router.agents.keys()
            }
        }
    
    # Store the api reference in app state for the router
    api.state.agent_router = router
    
    return app


# Default app instance
app = create_agui_app()


if __name__ == "__main__":
    print("🚀 Starting AG-UI Application...")
    print("📍 Available agents:")
    
    router = AgentRouter()
    for agent_name in router.agents.keys():
        print(f"   - {agent_name}: http://localhost:8000/agui/awp?agent={agent_name}")
    print("\n📍 List agents: http://localhost:8000/agui/agents")
    print("📍 API docs: http://localhost:8000/docs")
    
    # Get FastAPI instance (already created in create_agui_app)
    api = app.get_app(enable_agui=True)
    
    # Serve the application
    app.serve(api, host="0.0.0.0", port=8000)