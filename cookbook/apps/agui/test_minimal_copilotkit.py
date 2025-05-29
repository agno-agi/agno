#!/usr/bin/env python3
"""
Minimal test script to debug CopilotKit filterAdjacentAgentStateMessages error
"""

import json
import requests

def test_minimal_copilotkit():
    """Test with minimal payload"""
    url = "http://localhost:3000/api/copilotkit"
    
    # Minimal GraphQL mutation payload - no messages
    payload = {
        "operationName": "generateCopilotResponse",
        "variables": {
            "data": {
                "messages": [],  # Empty messages array
                "threadId": "test-minimal",
                "agentSession": {
                    "agentName": "agenticChatAgent",
                    "threadId": "test-minimal"
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
              }
              ... on AgentStateMessageOutput {
                threadId
                state
                running
                agentName
                role
              }
            }
          }
        }
        """
    }
    
    print("Testing minimal CopilotKit route...")
    print(f"URL: {url}")
    
    # Make the request
    response = requests.post(
        url,
        json=payload,
        headers={"Content-Type": "application/json"},
        stream=True
    )
    
    print(f"\nResponse status: {response.status_code}")
    
    if response.status_code == 200:
        print("\n✅ Request successful!")
        print("\nFirst 5 events:")
        print("-" * 80)
        
        event_count = 0
        for line in response.iter_lines(decode_unicode=True):
            if line and line.startswith("data: "):
                event_count += 1
                event_data = line[6:]
                
                if event_data == "[DONE]":
                    print(f"\nEvent {event_count}: [DONE]")
                    break
                    
                try:
                    data = json.loads(event_data)
                    print(f"\nEvent {event_count}:")
                    print(json.dumps(data, indent=2))
                    
                    if event_count >= 5:  # Only show first 5 events
                        print("\n... (truncated)")
                        break
                        
                except json.JSONDecodeError as e:
                    print(f"\nEvent {event_count}: Failed to parse - {e}")
    else:
        print(f"\n❌ Request failed with status {response.status_code}")
        print(f"Response: {response.text}")

if __name__ == "__main__":
    test_minimal_copilotkit() 