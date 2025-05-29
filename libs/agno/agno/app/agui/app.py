"""
AG-UI FastAPI Application

Main application that serves agents via the AG-UI protocol.
"""

from typing import Dict, Optional
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, Request

from agno.agent.agent import Agent
from agno.app.fastapi.app import FastAPIApp
from agno.team.team import Team


class AGUIApp(FastAPIApp):
    """AG-UI Application for serving agents with the AG-UI protocol"""

    def __init__(
        self,
        agent: Optional[Agent] = None,
        team: Optional[Team] = None,
        app_id: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ):
        """
        Initialize an AG-UI application.

        Args:
            agent: The Agno agent to serve
            team: The Agno team to serve (not yet implemented)
            app_id: Unique identifier for the app
            name: Name of the application
            description: Description of the application
        """
        super().__init__(
            agent=agent,
            team=team,
            app_id=app_id,
            name=name or "AG-UI App",
            description=description or "AG-UI Protocol Bridge Application",
        )

        # Store the agent for AG-UI router access
        if agent:
            self._agui_agent = agent

    def get_app(self) -> FastAPI:
        """Get the FastAPI app with AG-UI enabled"""
        # Always enable AG-UI for this app type
        app = super().get_app(enable_agui=True)

        # Store reference to agent for router
        if hasattr(self, "_agui_agent"):
            app._agui_agent = self._agui_agent

        return app

    def serve(
        self,
        app: str = None,
        host: str = "0.0.0.0",
        port: int = 8000,
        reload: bool = False,
        **kwargs,
    ):
        """
        Serve the AG-UI application.

        Args:
            app: App string (defaults to module:app format)
            host: Host to bind to
            port: Port to bind to
            reload: Enable auto-reload
            **kwargs: Additional uvicorn options
        """
        # Print startup info
        print("🚀 Starting AG-UI Application...")
        if self.agent:
            print(f"📍 Access the agent at:")
            print(f"   - http://localhost:{port}/agui/awp?agent={self.agent.name}")
            print(f"   - http://localhost:{port}/agui/awp?agent=agenticChatAgent")
        print(f"\n📍 List all agents: http://localhost:{port}/agui/agents")
        print(f"📍 API docs: http://localhost:{port}/docs")

        # Use module:app format if not provided
        if app is None:
            import inspect

            frame = inspect.stack()[1]
            module = inspect.getmodule(frame[0])
            if module and module.__name__ == "__main__":
                # Get the module file name without extension
                import os

                module_name = os.path.splitext(os.path.basename(module.__file__))[0]
                app = f"{module_name}:app"
            else:
                app = "app:app"

        super().serve(app=app, host=host, port=port, reload=reload, **kwargs)
