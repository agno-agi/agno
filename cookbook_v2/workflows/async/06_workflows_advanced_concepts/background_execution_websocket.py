import json
from typing import Any, Dict

import uvicorn
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.googlesearch import GoogleSearchTools
from agno.tools.hackernews import HackerNewsTools
from agno.workflow.v2.step import Step
from agno.workflow.v2.workflow import Workflow
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

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
    tools=[GoogleSearchTools()],
    instructions="Search for additional information on the web",
)

# === FASTAPI APP ===
app = FastAPI(title="Background Workflow WebSocket Demo")

# Store active WebSocket connections
active_connections: Dict[str, WebSocket] = {}


@app.get("/")
async def get():
    """Simple HTML client for testing background workflow execution"""
    return HTMLResponse("""
<!DOCTYPE html>
<html>
<head>
    <title>Background Workflow WebSocket Demo</title>
    <style>
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
            margin: 20px; 
            background-color: #f5f7fa;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            padding: 20px;
        }
        
        h1 {
            color: #2d3748;
            text-align: center;
            margin-bottom: 30px;
        }
        
        .controls {
            background: #f8fafc;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            border: 1px solid #e2e8f0;
        }
        
        input {
            padding: 12px 16px;
            width: 400px;
            border: 2px solid #e2e8f0;
            border-radius: 8px;
            font-size: 14px;
            margin-right: 10px;
        }
        
        input:focus {
            outline: none;
            border-color: #4299e1;
            box-shadow: 0 0 0 3px rgba(66, 153, 225, 0.1);
        }
        
        button {
            padding: 12px 24px;
            margin: 5px;
            border: none;
            border-radius: 8px;
            font-weight: 600;
            cursor: pointer;
            font-size: 14px;
            transition: all 0.2s;
        }
        
        .btn-primary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        
        .btn-primary:hover {
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
        }
        
        .btn-secondary {
            background: #e2e8f0;
            color: #4a5568;
        }
        
        .btn-secondary:hover {
            background: #cbd5e0;
        }
        
        .status-bar {
            padding: 12px 16px;
            border-radius: 8px;
            margin-bottom: 20px;
            font-weight: 600;
            text-align: center;
        }
        
        .status-connected {
            background: #c6f6d5;
            color: #22543d;
            border: 1px solid #9ae6b4;
        }
        
        .status-disconnected {
            background: #fed7d7;
            color: #742a2a;
            border: 1px solid #fc8181;
        }
        
        #messages {
            border: 1px solid #e2e8f0;
            height: 500px;
            overflow-y: auto;
            padding: 16px;
            margin: 20px 0;
            background: white;
            border-radius: 8px;
            font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
            font-size: 13px;
            line-height: 1.5;
        }
        
        .message {
            margin: 8px 0;
            padding: 12px 16px;
            border-radius: 8px;
            border-left: 4px solid;
            position: relative;
            animation: slideIn 0.3s ease-out;
        }
        
        @keyframes slideIn {
            from {
                opacity: 0;
                transform: translateX(-10px);
            }
            to {
                opacity: 1;
                transform: translateX(0);
            }
        }
        
        .message-icon {
            display: inline-block;
            width: 20px;
            margin-right: 8px;
            font-weight: bold;
        }
        
        .message-time {
            color: #718096;
            font-size: 11px;
            margin-right: 8px;
        }
        
        .message-content {
            font-weight: 500;
        }
        
        .event-type {
            background: rgba(0, 0, 0, 0.1);
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: 600;
            margin-left: 8px;
            color: rgba(0, 0, 0, 0.7);
        }
        
        /* Event Type Styles */
        .workflow_started {
            background: linear-gradient(135deg, #e6fffa 0%, #b2f5ea 100%);
            border-left-color: #38b2ac;
            color: #234e52;
        }
        
        .step_started {
            background: linear-gradient(135deg, #fefcbf 0%, #faf089 100%);
            border-left-color: #d69e2e;
            color: #744210;
        }
        
        .step_completed {
            background: linear-gradient(135deg, #f0fff4 0%, #c6f6d5 100%);
            border-left-color: #38a169;
            color: #22543d;
        }
        
        .workflow_completed {
            background: linear-gradient(135deg, #ebf8ff 0%, #bee3f8 100%);
            border-left-color: #3182ce;
            color: #2a4365;
        }
        
        .workflow_error {
            background: linear-gradient(135deg, #fed7d7 0%, #feb2b2 100%);
            border-left-color: #e53e3e;
            color: #742a2a;
        }
        
        .info {
            background: linear-gradient(135deg, #f7fafc 0%, #edf2f7 100%);
            border-left-color: #718096;
            color: #2d3748;
        }
        
        .background-event {
            position: relative;
        }
        
        .background-event::before {
            content: "🚀";
            position: absolute;
            top: 12px;
            right: 16px;
            font-size: 16px;
        }
        
        .message-detail {
            margin-top: 6px;
            font-size: 12px;
            opacity: 0.8;
            font-style: italic;
            background: rgba(255, 255, 255, 0.3);
            padding: 4px 8px;
            border-radius: 4px;
        }
        
        .content-preview {
            margin-top: 6px;
            font-size: 11px;
            background: rgba(0, 0, 0, 0.05);
            padding: 6px 8px;
            border-radius: 4px;
            border-left: 2px solid rgba(0, 0, 0, 0.2);
            font-family: monospace;
            max-height: 60px;
            overflow-y: auto;
        }
        
        /* Scrollbar styling */
        #messages::-webkit-scrollbar, .content-preview::-webkit-scrollbar {
            width: 6px;
        }
        
        #messages::-webkit-scrollbar-track, .content-preview::-webkit-scrollbar-track {
            background: #f1f1f1;
            border-radius: 4px;
        }
        
        #messages::-webkit-scrollbar-thumb, .content-preview::-webkit-scrollbar-thumb {
            background: #c1c1c1;
            border-radius: 4px;
        }
        
        #messages::-webkit-scrollbar-thumb:hover, .content-preview::-webkit-scrollbar-thumb:hover {
            background: #a8a8a8;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🚀 Background Workflow Demo</h1>
        
        <div class="controls">
            <input type="text" id="messageInput" placeholder="Enter your research topic..." value="AI trends 2024">
            <button class="btn-primary" onclick="startWorkflowBackgroundStream()">🚀 Start Background Streaming</button>
            <button class="btn-secondary" onclick="clearMessages()">🗑️ Clear Messages</button>
        </div>
        
        <div id="status" class="status-bar status-disconnected">Status: Disconnected</div>
        <div id="messages"></div>
    </div>
    <script>
        let ws = null;
        function connect() {
            ws = new WebSocket('ws://localhost:8000/ws');
            
            ws.onopen = function(event) {
                const statusEl = document.getElementById('status');
                statusEl.textContent = 'Status: Connected ✅';
                statusEl.className = 'status-bar status-connected';
                console.log('WebSocket connected');
            };
            
            ws.onmessage = function(event) {
                const data = JSON.parse(event.data);
                console.log('Received event:', data);
                displayMessage(data);
            };
            
            ws.onclose = function(event) {
                const statusEl = document.getElementById('status');
                statusEl.textContent = 'Status: Disconnected ❌';
                statusEl.className = 'status-bar status-disconnected';
                console.log('WebSocket disconnected');
            };
            
            ws.onerror = function(error) {
                console.log('WebSocket error:', error);
                displayMessage({type: 'workflow_error', content: 'WebSocket error: ' + error});
            };
        }
        function getEventIcon(eventType) {
            const icons = {
                'WorkflowStartedEvent': '🚀',
                'StepStartedEvent': '⏳',
                'StepCompletedEvent': '✅',
                'WorkflowCompletedEvent': '🎉',
                'WorkflowErrorEvent': '❌',
                'info': 'ℹ️',
                'connection_established': '🔌',
                'echo': '📡',
                'error': '❌'
            };
            return icons[eventType] || '📝';
        }
        function getEventStyle(eventType) {
            const styles = {
                'WorkflowStartedEvent': 'workflow_started',
                'StepStartedEvent': 'step_started', 
                'StepCompletedEvent': 'step_completed',
                'WorkflowCompletedEvent': 'workflow_completed',
                'WorkflowErrorEvent': 'workflow_error',
                'info': 'info',
                'connection_established': 'info',
                'echo': 'info',
                'error': 'workflow_error'
            };
            return styles[eventType] || 'info';
        }
        function displayMessage(data) {
            const messages = document.getElementById('messages');
            const messageDiv = document.createElement('div');
            
            // Determine the actual event type
            const eventType = data.event || data.type || 'unknown';
            const messageStyle = getEventStyle(eventType);
            const icon = getEventIcon(eventType);
            
            messageDiv.className = `message ${messageStyle}`;
            
            // Add background indicator for background events
            if (data.background) {
                messageDiv.classList.add('background-event');
            }
            
            const timestamp = new Date().toLocaleTimeString();
            
            let content = '';
            let details = [];
            let contentPreview = '';
            
            // Handle different event types
            switch(eventType) {
                case 'WorkflowStarted':
                    content = `Workflow Started: ${data.workflow_name || 'Unknown'}`;
                    if (data.run_id) details.push(`Run ID: ${data.run_id}`);
                    if (data.session_id) details.push(`Session: ${data.session_id}`);
                    break;
                    
                case 'StepStarted':
                    content = `Step Started: ${data.step_name || 'Unknown'}`;
                    if (data.step_index !== undefined) details.push(`Index: ${data.step_index}`);
                    break;
                    
                case 'StepCompleted':
                    content = `Step Completed: ${data.step_name || 'Unknown'}`;
                    if (data.step_index !== undefined) details.push(`Index: ${data.step_index}`);
                    if (data.content && typeof data.content === 'string') {
                        contentPreview = data.content.substring(0, 200);
                        if (data.content.length > 200) contentPreview += '...';
                    }
                    break;
                    
                case 'WorkflowCompleted':
                    content = `Workflow Completed!`;
                    if (data.status) details.push(`Status: ${data.status}`);
                    if (data.content && typeof data.content === 'string') {
                        contentPreview = data.content.substring(0, 200);
                        if (data.content.length > 200) contentPreview += '...';
                    }
                    break;
                    
                case 'WorkflowError':
                    content = `Workflow Error: ${data.error || 'Unknown error'}`;
                    break;
                    
                case 'connection_established':
                    content = 'Connected to workflow events';
                    if (data.connection_id) details.push(`Connection: ${data.connection_id}`);
                    break;
                    
                case 'info':
                    content = data.content || data.message || 'Info message';
                    break;
                    
                case 'echo':
                    content = 'Echo response received';
                    break;
                    
                default:
                    content = data.message || data.content || 'Unknown event';
                    // Show raw data for debugging
                    contentPreview = JSON.stringify(data, null, 2);
            }
            
            // Build the message HTML
            let messageHTML = `
                <span class="message-icon">${icon}</span>
                <span class="message-time">[${timestamp}]</span>
                <span class="message-content">${content}</span>
                <span class="event-type">${eventType}</span>
            `;
            
            if (details.length > 0) {
                messageHTML += `<div class="message-detail">${details.join(' • ')}</div>`;
            }
            
            if (contentPreview) {
                messageHTML += `<div class="content-preview">${contentPreview}</div>`;
            }
            
            messageDiv.innerHTML = messageHTML;
            messages.appendChild(messageDiv);
            messages.scrollTop = messages.scrollHeight;
        }
        async function startWorkflowBackgroundStream() {
            const message = document.getElementById('messageInput').value;
            if (!message.trim()) {
                alert('Please enter a research topic');
                return;
            }
            try {
                const response = await fetch('/workflow/background-stream', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        message: message,
                        session_id: 'demo-session-' + Date.now()
                    })
                });
                const result = await response.json();
                
                if (result.status === 'started') {
                    displayMessage({
                        type: 'info', 
                        content: `Background streaming workflow started: ${result.run_id}`,
                        message: 'Watch for real-time events!'
                    });
                } else {
                    displayMessage({
                        type: 'error', 
                        content: `Failed to start: ${result.message}`
                    });
                }
            } catch (error) {
                displayMessage({
                    type: 'error', 
                    content: `Failed to start background streaming workflow: ${error.message}`
                });
            }
        }
        function clearMessages() {
            document.getElementById('messages').innerHTML = '';
        }
        // Connect on page load
        connect();
    </script>
</body>
</html>
    """)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for background workflow events"""
    await websocket.accept()
    connection_id = f"conn_{len(active_connections)}"
    active_connections[connection_id] = websocket

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
                # Echo back for testing
                await websocket.send_text(
                    json.dumps({"type": "echo", "original_message": json.loads(data)})
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


@app.post("/workflow/background-stream")
async def run_workflow_background_stream(request: Dict[str, Any]):
    """Run workflow in background with streaming and WebSocket broadcasting"""
    message = request.get("message", "AI trends 2024")
    session_id = request.get("session_id")

    # Get the first available WebSocket connection for broadcasting
    websocket_conn = None
    if active_connections:
        websocket_conn = list(active_connections.values())[0]
    else:
        return {
            "status": "error",
            "message": "No WebSocket connection available for background streaming",
        }

    workflow = Workflow(
        name="Tech Research Pipeline",
        steps=[
            Step(name="hackernews_research", agent=hackernews_agent),
            Step(name="web_search", agent=search_agent),
        ],
        db=SqliteDb(
            db_file="tmp/workflow_v2_bg.db",
            session_table="workflow_v2_bg",
        ),
    )

    try:
        # Execute workflow in background with streaming and WebSocket
        result = await workflow.arun(
            message=message,
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
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    print("🚀 Starting Background Workflow WebSocket Server...")
    print("📊 Dashboard: http://localhost:8000")
    print("🔌 WebSocket: ws://localhost:8000/ws")
    print("📡 API Docs: http://localhost:8000/docs")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
