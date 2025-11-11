import json
import os
from typing import Dict

import uvicorn
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

# === CONFIGURATION ===
SECURITY_KEY = os.getenv("SECURITY_KEY", "your-secret-key")  # Set your key here

# === WORKFLOW SETUP ===
hackernews_agent = Agent(
    name="HackerNews Researcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[HackerNewsTools()],
    instructions="Research tech news and trends from HackerNews",
)

search_agent = Agent(
    name="Search Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    instructions="Search for additional information on the web",
)

# === FASTAPI APP ===
app = FastAPI(title="Background Workflow WebSocket Server")

# Store active WebSocket connections and their auth status
active_connections: Dict[str, WebSocket] = {}
authenticated_connections: Dict[str, bool] = {}  # {connection_id: is_authenticated}


def validate_token(token: str) -> bool:
    """Validate authentication token"""
    # If no security key set, allow all connections
    if not SECURITY_KEY or SECURITY_KEY == "your-secret-key":
        return True
    return token == SECURITY_KEY


@app.get("/")
async def get():
    """API status endpoint"""
    return {
        "status": "running",
        "message": "Background Workflow WebSocket Server",
        "endpoints": {
            "websocket": "/ws",
            "start-workflow": "/workflow/start",
        },
        "connections": len(active_connections),
        "authenticated": len([c for c in authenticated_connections.values() if c]),
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for background workflow events"""
    await websocket.accept()
    connection_id = f"conn_{len(active_connections)}"
    active_connections[connection_id] = websocket
    authenticated_connections[connection_id] = False  # Start unauthenticated

    print(f"🔌 Client connected: {connection_id}")

    try:
        # Send connection confirmation
        await websocket.send_text(
            json.dumps(
                {
                    "event": "connected",
                    "connection_id": connection_id,
                    "message": "Connected to workflow events. Please authenticate to continue.",
                    "requires_auth": True,
                }
            )
        )

        # Keep connection alive
        while True:
            try:
                data = await websocket.receive_text()
                message_data = json.loads(data)
                action = message_data.get("action") or message_data.get("type")

                # Handle authentication
                if action == "authenticate":
                    token = message_data.get("token")
                    if not token:
                        await websocket.send_text(
                            json.dumps(
                                {"event": "auth_error", "error": "Token is required"}
                            )
                        )
                        continue

                    if validate_token(token):
                        authenticated_connections[connection_id] = True
                        await websocket.send_text(
                            json.dumps(
                                {
                                    "event": "authenticated",
                                    "message": "Authentication successful. You can now send commands.",
                                }
                            )
                        )
                        print(f"🔐 Client authenticated: {connection_id}")
                    else:
                        await websocket.send_text(
                            json.dumps(
                                {"event": "auth_error", "error": "Invalid token"}
                            )
                        )
                    continue

                # Check authentication for other actions
                if not authenticated_connections.get(connection_id, False):
                    await websocket.send_text(
                        json.dumps(
                            {
                                "event": "auth_required",
                                "error": "Authentication required. Send authenticate action with valid token.",
                            }
                        )
                    )
                    continue

                # Handle authenticated actions
                if action == "start-workflow":
                    await handle_start_workflow(websocket, message_data)
                elif action == "ping":
                    await websocket.send_text(json.dumps({"event": "pong"}))
                else:
                    # Echo back for testing
                    await websocket.send_text(
                        json.dumps({"event": "echo", "original_message": message_data})
                    )

            except WebSocketDisconnect:
                break
            except Exception as e:
                await websocket.send_text(
                    json.dumps(
                        {
                            "event": "error",
                            "message": f"Error processing message: {str(e)}",
                        }
                    )
                )

    except WebSocketDisconnect:
        pass
    finally:
        if connection_id in active_connections:
            del active_connections[connection_id]
        if connection_id in authenticated_connections:
            del authenticated_connections[connection_id]
        print(f"🔌 Client disconnected: {connection_id}")


async def handle_start_workflow(websocket: WebSocket, message_data: dict):
    """Handle workflow start request via WebSocket"""
    message = message_data.get("message", "AI trends 2024")
    session_id = message_data.get("session_id", f"ws-session-{len(active_connections)}")

    workflow = Workflow(
        name="Tech Research Pipeline",
        steps=[
            Step(name="hackernews_research", agent=hackernews_agent),
            Step(name="web_search", agent=search_agent),
        ],
        db=SqliteDb(
            db_file="tmp/workflow_bg.db",
            session_table="workflow_bg",
        ),
    )

    try:
        # Send acknowledgment
        await websocket.send_text(
            json.dumps(
                {
                    "event": "workflow_starting",
                    "message": f"Starting workflow with message: {message}",
                    "session_id": session_id,
                }
            )
        )

        # Execute workflow in background with streaming and WebSocket
        result = await workflow.arun(
            input=message,
            session_id=session_id,
            stream=True,
            stream_events=True,
            background=True,
            websocket=websocket,
        )

        # Send completion notification
        await websocket.send_text(
            json.dumps(
                {
                    "event": "workflow_initiated",
                    "run_id": result.run_id,
                    "session_id": result.session_id,
                    "message": "Background streaming workflow initiated successfully",
                }
            )
        )

    except Exception as e:
        await websocket.send_text(
            json.dumps(
                {
                    "event": "workflow_error",
                    "error": str(e),
                    "message": "Failed to start workflow",
                }
            )
        )


# ... rest of the HTTP endpoint code stays the same ...

if __name__ == "__main__":
    print("🚀 Starting Background Workflow WebSocket Server...")
    print("🔌 WebSocket: ws://localhost:8000/ws")
    print("📡 HTTP API: http://localhost:8000")
    print("📊 API Docs: http://localhost:8000/docs")
    print(f"🔐 Security Key: {SECURITY_KEY}")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
