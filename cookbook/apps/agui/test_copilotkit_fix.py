#!/usr/bin/env python3
"""
Test script to verify the CopilotKit route fix for filterAdjacentAgentStateMessages error
"""

import json
import requests

def parse_sse_event(line):
    """Parse a single SSE event line"""
    if line.startswith("data: "):
        return line[6:]  # Remove "data: " prefix
    return None

def test_copilotkit_route():
    """Test the CopilotKit route with a simple message"""
    url = "http://localhost:3000/api/copilotkit"
    
    # GraphQL mutation payload
    payload = {
        "operationName": "generateCopilotResponse",
        "variables": {
            "data": {
                "messages": [{
                    "id": "msg-test-1",
                    "textMessage": {
                        "role": "user",
                        "content": "Hello"
                    }
                }],
                "threadId": "test-thread-fix",
                "agentSession": {
                    "agentName": "agenticChatAgent",
                    "threadId": "test-thread-fix"
                },
                "agentStates": []
            }
        },
        "query": """
        mutation generateCopilotResponse($data: GenerateCopilotResponseInput!) {
          generateCopilotResponse(data: $data) {
            threadId
            runId
            messages @stream {
              __typename
              ... on TextMessageOutput {
                id
                content @stream
                role
                status {
                  code
                  __typename
                }
              }
              ... on AgentStateMessageOutput {
                threadId
                state
                running
                agentName
                nodeName
                runId
                active
                role
                __typename
              }
            }
            status {
              code
              __typename
            }
          }
        }
        """
    }
    
    print("Testing CopilotKit route...")
    print(f"URL: {url}")
    
    # Make the request with streaming
    response = requests.post(
        url,
        json=payload,
        headers={"Content-Type": "application/json"},
        stream=True
    )
    
    print(f"\nResponse status: {response.status_code}")
    print(f"Response headers: {dict(response.headers)}")
    
    if response.status_code == 200:
        print("\n✅ Request successful!")
        print("\nStreaming events:")
        print("-" * 80)
        
        event_count = 0
        messages_received = []
        agent_states_received = []
        
        # Read the response line by line
        for line in response.iter_lines(decode_unicode=True):
            if line:
                event_data = parse_sse_event(line)
                if event_data:
                    event_count += 1
                    
                    if event_data == "[DONE]":
                        print(f"\nEvent {event_count}: [DONE]")
                        break
                    
                    try:
                        data = json.loads(event_data)
                        print(f"\nEvent {event_count}:")
                        print(json.dumps(data, indent=2))
                        
                        # Track messages and agent states
                        if "data" in data and "generateCopilotResponse" in data["data"]:
                            response_data = data["data"]["generateCopilotResponse"]
                            if "messages" in response_data:
                                for msg in response_data["messages"]:
                                    if msg.get("__typename") == "TextMessageOutput":
                                        messages_received.append(msg)
                                    elif msg.get("__typename") == "AgentStateMessageOutput":
                                        agent_states_received.append(msg)
                    
                    except json.JSONDecodeError as e:
                        print(f"\nEvent {event_count}: Failed to parse JSON - {e}")
                        print(f"Raw data: {event_data}")
        
        print("\n" + "-" * 80)
        print(f"\nTotal events received: {event_count}")
        print(f"Text messages received: {len(messages_received)}")
        print(f"Agent state messages received: {len(agent_states_received)}")
        
        # Verify we received at least one agent state message
        if agent_states_received:
            print("\n✅ Agent state messages present - filterAdjacentAgentStateMessages should work")
            print(f"   First agent state: {json.dumps(agent_states_received[0], indent=2)}")
        else:
            print("\n⚠️  No agent state messages received - this might cause the error")
            
        # Show final message content
        if messages_received:
            final_content = max(messages_received, key=lambda m: len(m.get("content", "")))
            print(f"\nFinal message content: {final_content.get('content', '')}")
            
    else:
        print(f"\n❌ Request failed with status {response.status_code}")
        print(f"Response: {response.text}")

if __name__ == "__main__":
    test_copilotkit_route() 