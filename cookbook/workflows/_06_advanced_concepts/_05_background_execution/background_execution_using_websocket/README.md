# WebSocket Background Workflow Execution

This example demonstrates how to execute Agno workflows in the background with real-time streaming events via WebSocket connections. It features a clean WebSocket server and a beautiful CLI client with rich formatting for monitoring workflow progress.

## Overview

The WebSocket approach provides:
- **Real-time streaming** of workflow events and content
- **Background execution** - workflows run independently of client connections
- **Beautiful CLI interface** with color-coded events and emojis

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

### 2. Run the CLI Client

**Interactive Mode** (recommended):
```bash
python websocket_client.py -i
```

Then enter any message you want, for example: `start AI Trends`

**Single Command Mode**:
```bash
python websocket_client.py -m "Research the latest AI developments in 2024"
```

## Usage

You can similarly integrate it in your own frontend using this websocket approach.