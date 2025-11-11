# WebSocket Background Workflow Execution

This example demonstrates how to execute Agno workflows in the background with real-time streaming events via WebSocket connections. It features a clean WebSocket server and a beautiful CLI client with rich formatting for monitoring workflow progress.

## Overview

The WebSocket approach provides:
- **Real-time streaming** of workflow events and content
- **Background execution** - workflows run independently of client connections
- **Beautiful CLI interface** with color-coded events and emojis
- **Secure authentication** using bearer tokens

## Files

- `websocket_server.py` - WebSocket server for background workflow execution
- `websocket_client.py` - Rich CLI client for real-time event monitoring

## ⚡ Quick Start

### 1. Start the WebSocket Server

```bash
cd cookbook/workflows/_06_advanced_concepts/_05_background_execution/background_execution_using_websocket/
python websocket_server.py
```

The server will start on `http://localhost:8000` with WebSocket endpoint at `ws://localhost:8000/ws`

### 2. Set Authentication (if required)

If you are using your workflow in an AgentOS instance that requires authentication, set your security key:

```bash
export SECURITY_KEY="your_security_key_here"
```

or pass it directly with the `--token` flag.

### 3. Run the CLI Client

**Interactive Mode** (recommended):
```bash
# Using environment variable
python websocket_client.py -i

# Or using token flag
python websocket_client.py -i --token "your_security_key_here"
```

Then enter any message you want, for example: `start AI Trends`

**Single Command Mode**:
```bash
# Using environment variable
python websocket_client.py -m "Research the latest AI developments in 2024"

# Or using token flag  
python websocket_client.py -m "Research the latest AI developments" --token "your_security_key_here"
```

## Authentication

The WebSocket client supports secure authentication using bearer tokens:

1. **Environment Variable**: Set `OS_SECURITY_KEY` environment variable
2. **Command Line**: Use `--token` or `-t` flag to pass the token directly
3. **Automatic Authentication**: The client automatically sends the auth token after connecting

If no token is provided and the server requires authentication, you'll see authentication error messages.

## Usage

You can similarly integrate it in your own frontend using this websocket approach.