#!/usr/bin/env python3
"""
Simple Demo Client for AG-UI Bridge

This script demonstrates how to interact with Agno agents via the AG-UI protocol.
"""
import asyncio
import httpx
import json
from typing import List, Dict, Any


async def stream_agent_response(
    agent_name: str,
    message: str,
    base_url: str = "http://localhost:8000"
) -> str:
    """Stream a response from an Agno agent via AG-UI protocol"""
    
    url = f"{base_url}/agui/awp?agent={agent_name}"
    
    # Create AG-UI protocol request
    request_data = {
        "messages": [
            {
                "id": "msg-1",
                "role": "user",
                "content": message
            }
        ],
        "threadId": "demo-thread-1",
        "runId": "demo-run-1",
        "state": {},
        "tools": [],
        "context": [],
        "forwardedProps": {}
    }
    
    print(f"\n🤖 Agent: {agent_name}")
    print(f"💬 You: {message}")
    print(f"🤖 Assistant: ", end="", flush=True)
    
    full_response = ""
    
    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST",
            url,
            json=request_data,
            headers={"Content-Type": "application/json"}
        ) as response:
            if response.status_code != 200:
                print(f"\n❌ Error: {response.status_code}")
                return ""
            
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    event_data = line[6:]
                    if event_data == "[DONE]":
                        break
                    
                    try:
                        event = json.loads(event_data)
                        
                        # Handle text content events
                        if event.get("type") == "TEXT_MESSAGE_CONTENT":
                            delta = event.get("delta", "")
                            print(delta, end="", flush=True)
                            full_response += delta
                            
                    except json.JSONDecodeError:
                        pass
    
    print("\n")
    return full_response


async def demo_frontend_tools():
    """Demonstrate frontend tool execution"""
    
    print("\n📋 Frontend Tools Demo")
    print("=" * 50)
    
    url = "http://localhost:8000/agui/awp?agent=human_in_loop_agent"
    
    # Request with frontend tool defined
    request_data = {
        "messages": [
            {
                "id": "msg-1",
                "role": "user",
                "content": "Can you help me delete all temporary files?"
            }
        ],
        "threadId": "demo-thread-2",
        "runId": "demo-run-2",
        "state": {},
        "tools": [
            {
                "name": "confirmAction",
                "description": "Get user confirmation for dangerous actions",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "Action to confirm"},
                        "reason": {"type": "string", "description": "Reason for the action"}
                    },
                    "required": ["action"]
                }
            }
        ],
        "context": [],
        "forwardedProps": {}
    }
    
    print("💬 User: Can you help me delete all temporary files?")
    print("\n🤖 Assistant response:")
    
    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST",
            url,
            json=request_data,
            headers={"Content-Type": "application/json"}
        ) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    event_data = line[6:]
                    if event_data == "[DONE]":
                        break
                    
                    try:
                        event = json.loads(event_data)
                        
                        # Show different event types
                        if event.get("type") == "TEXT_MESSAGE_CONTENT":
                            print(event.get("delta", ""), end="", flush=True)
                        elif event.get("type") == "TOOL_CALL_START":
                            print(f"\n\n🔧 Tool Call: {event.get('name')}")
                        elif event.get("type") == "TOOL_CALL_ARGS":
                            print(f"   Args: {event.get('args')}")
                            
                    except json.JSONDecodeError:
                        pass
    
    print("\n\n💡 Note: In a real frontend, the tool call would trigger a UI confirmation dialog")


async def main():
    """Run demo interactions with different agents"""
    
    print("🚀 AG-UI Bridge Demo Client")
    print("=" * 50)
    
    # Test different agents
    demos = [
        ("chat_agent", "What's the weather like today?"),
        ("generative_ui_agent", "Create a simple counter component"),
        ("tool_ui_agent", "Generate a haiku about coding"),
        ("shared_state_agent", "Make a recipe for pancakes")
    ]
    
    for agent, message in demos:
        await stream_agent_response(agent, message)
        await asyncio.sleep(1)
    
    # Demo frontend tools
    await demo_frontend_tools()
    
    print("\n✅ Demo completed!")


if __name__ == "__main__":
    print("ℹ️  Make sure the backend is running: python cookbook/apps/agui/basic.py")
    asyncio.run(main()) 