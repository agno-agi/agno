import json
from typing import Any, Dict

import uvicorn
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

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

# Store active WebSocket connections
active_connections: Dict[str, WebSocket] = {}


@app.get("/")
async def get():
    """API status endpoint"""
    return {
        "status": "running",
        "message": "Background Workflow WebSocket Server",
        "endpoints": {
            "websocket": "/ws",
            "start_workflow": "/workflow/start",
        },
        "connections": len(active_connections),
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for background workflow events"""
    await websocket.accept()
    connection_id = f"conn_{len(active_connections)}"
    active_connections[connection_id] = websocket

    print(f"🔌 Client connected: {connection_id}")

    try:
        await websocket.send_text(
            json.dumps(
                {
                    "type": "connection_established",
                    "connection_id": connection_id,
                    "message": "Connected to background workflow events",
                }
            )
        )

        # Keep connection alive
        while True:
            try:
                data = await websocket.receive_text()
                message_data = json.loads(data)

                # Handle incoming messages
                if message_data.get("type") == "start_workflow":
                    await handle_start_workflow(websocket, message_data)
                elif message_data.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
                else:
                    # Echo back for testing
                    await websocket.send_text(
                        json.dumps({"type": "echo", "original_message": message_data})
                    )

            except WebSocketDisconnect:
                break
            except Exception as e:
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "error",
                            "message": f"Error processing message: {str(e)}",
                        }
                    )
                )

    except WebSocketDisconnect:
        pass
    finally:
        if connection_id in active_connections:
            del active_connections[connection_id]
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
                    "type": "workflow_starting",
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
            stream_intermediate_steps=True,
            background=True,
            websocket=websocket,
        )

        # Send completion notification
        await websocket.send_text(
            json.dumps(
                {
                    "type": "workflow_initiated",
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
                    "type": "workflow_error",
                    "error": str(e),
                    "message": "Failed to start workflow",
                }
            )
        )


@app.post("/workflow/start")
async def start_workflow_http(request: Dict[str, Any]):
    """HTTP endpoint to start workflow (requires WebSocket connection)"""
    message = request.get("message", "AI trends 2024")
    session_id = request.get("session_id")

    # Get the first available WebSocket connection for broadcasting
    websocket_conn = None
    if active_connections:
        websocket_conn = list(active_connections.values())[0]
    else:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": "No WebSocket connection available for background streaming",
            },
        )

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
        # Execute workflow in background with streaming and WebSocket
        result = await workflow.arun(
            input=message,
            session_id=session_id,
            stream=True,
            stream_intermediate_steps=True,
            background=True,
            websocket=websocket_conn,
        )

        return {
            "status": "started",
            "run_id": result.run_id,
            "session_id": result.session_id,
            "message": "Background streaming workflow started - events will be broadcast via WebSocket",
        }

    except Exception as e:
        return JSONResponse(
            status_code=500, content={"status": "error", "message": str(e)}
        )


if __name__ == "__main__":
    print("🚀 Starting Background Workflow WebSocket Server...")
    print("🔌 WebSocket: ws://localhost:8000/ws")
    print("📡 HTTP API: http://localhost:8000")
    print("📊 API Docs: http://localhost:8000/docs")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
