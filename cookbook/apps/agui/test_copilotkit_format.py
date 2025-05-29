#!/usr/bin/env python3
"""
Test CopilotKit GraphQL Format

This script tests how the CopilotKit API route formats AG-UI events.
"""
import asyncio
import httpx
import json


async def test_copilotkit_format():
    """Test the CopilotKit GraphQL format"""
    
    url = "http://localhost:3000/api/copilotkit"
    
    # Create a CopilotKit-style GraphQL request
    request_data = {
        "variables": {
            "data": {
                "messages": [
                    {
                        "id": "msg-1",
                        "textMessage": {
                            "role": "user",
                            "content": "Hello!"
                        }
                    }
                ],
                "threadId": "test-thread-123",
                "runId": "test-run-123",
                "agentSession": {
                    "agentName": "agenticChatAgent",
                    "threadId": "test-thread-123"
                },
                "agentStates": []
            }
        }
    }
    
    print("🧪 Testing CopilotKit GraphQL format...")
    print("📍 URL:", url)
    print("📝 Request:", json.dumps(request_data, indent=2))
    print("\n📤 Response:")
    print("-" * 50)
    
    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST",
            url,
            json=request_data,
            headers={"Content-Type": "application/json"},
            timeout=30.0
        ) as response:
            if response.status_code != 200:
                print(f"❌ Error: {response.status_code}")
                error_text = await response.aread()
                print(f"Error details: {error_text.decode()}")
                return
            
            event_count = 0
            async for line in response.aiter_lines():
                if line.strip():
                    event_count += 1
                    print(f"\nEvent {event_count}:")
                    try:
                        data = json.loads(line)
                        print(json.dumps(data, indent=2))
                        
                        # Check content format
                        messages = data.get("data", {}).get("generateCopilotResponse", {}).get("messages", [])
                        for msg in messages:
                            content = msg.get("content")
                            if content is not None:
                                print(f"  Content type: {type(content).__name__}")
                                print(f"  Content value: {repr(content)}")
                                
                    except json.JSONDecodeError:
                        print(f"  Raw: {line}")
                    
                    # Limit output for readability
                    if event_count >= 10:
                        print("\n... (showing first 10 events)")
                        break
    
    print("-" * 50)
    print("✅ Test complete!")


if __name__ == "__main__":
    print("ℹ️  Make sure both backend and frontend are running:")
    print("   Backend: python cookbook/apps/agui/basic.py")
    print("   Frontend: cd dojo && npm run dev")
    print()
    asyncio.run(test_copilotkit_format()) 