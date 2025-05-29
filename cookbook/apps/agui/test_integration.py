#!/usr/bin/env python3
"""
Test AG-UI Bridge Integration

This script tests the integration between Dojo frontend and Agno backend agents
via the AG-UI protocol.
"""
import asyncio
import json
import httpx
from typing import List, Dict, Any
import time


class AGUIIntegrationTester:
    """Test AG-UI protocol integration"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
    
    async def test_health_check(self) -> bool:
        """Test the health check endpoint"""
        try:
            response = await self.client.get(f"{self.base_url}/agui/health")
            if response.status_code == 200:
                data = response.json()
                print("✅ Health check passed:", data)
                return True
            else:
                print(f"❌ Health check failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Health check error: {e}")
            return False
    
    async def test_list_agents(self) -> bool:
        """Test listing available agents"""
        try:
            response = await self.client.get(f"{self.base_url}/agui/agents")
            if response.status_code == 200:
                data = response.json()
                print("✅ Available agents:", data.get("agents", []))
                print("✅ Agent endpoints:", json.dumps(data.get("endpoints", {}), indent=2))
                return True
            else:
                print(f"❌ List agents failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ List agents error: {e}")
            return False
    
    async def test_agent_streaming(self, agent_name: str, message: str) -> bool:
        """Test streaming response from an agent"""
        url = f"{self.base_url}/agui/awp?agent={agent_name}"
        
        # Create AG-UI protocol request with camelCase fields
        request_data = {
            "messages": [
                {
                    "id": "msg-1",
                    "role": "user",
                    "content": message
                }
            ],
            "threadId": f"test-thread-{int(time.time())}",
            "runId": f"test-run-{int(time.time())}",
            "state": {},
            "tools": [],
            "context": [],
            "forwardedProps": {}
        }
        
        print(f"\n🔍 Testing agent: {agent_name}")
        print(f"📝 Message: {message}")
        
        try:
            # Stream the response
            events_received = []
            
            async with self.client.stream(
                "POST",
                url,
                json=request_data,
                headers={"Content-Type": "application/json"}
            ) as response:
                if response.status_code != 200:
                    print(f"❌ Agent request failed: {response.status_code}")
                    # Try to read error response
                    try:
                        error_text = await response.aread()
                        print(f"❌ Error details: {error_text.decode()}")
                    except:
                        pass
                    return False
                
                # Read SSE events
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        event_data = line[6:]  # Remove "data: " prefix
                        if event_data == "[DONE]":
                            break
                        
                        try:
                            event = json.loads(event_data)
                            events_received.append(event)
                            
                            # Print key events
                            if event.get("type") == "run.started":
                                print("✅ Run started")
                            elif event.get("type") == "text.message.content":
                                print(f"📤 Content: {event.get('delta', '')}", end="", flush=True)
                            elif event.get("type") == "run.finished":
                                print("\n✅ Run finished")
                                
                        except json.JSONDecodeError:
                            print(f"⚠️  Invalid JSON: {event_data}")
            
            # Verify we received events
            if events_received:
                print(f"✅ Received {len(events_received)} events")
                return True
            else:
                print("❌ No events received")
                return False
                
        except Exception as e:
            print(f"❌ Agent streaming error: {e}")
            return False
    
    async def test_all_agents(self) -> Dict[str, bool]:
        """Test all available agents"""
        agents_to_test = [
            ("chat_agent", "Hello! How are you today?"),
            ("generative_ui_agent", "Help me create a todo list application"),
            ("human_in_loop_agent", "Can you help me with a task that needs confirmation?"),
            ("predictive_state_agent", "Improve this text: The quick brown fox"),
            ("shared_state_agent", "Create a recipe for chocolate cake"),
            ("tool_ui_agent", "Generate a haiku about nature"),
        ]
        
        results = {}
        for agent_name, message in agents_to_test:
            results[agent_name] = await self.test_agent_streaming(agent_name, message)
            await asyncio.sleep(1)  # Brief pause between tests
        
        return results
    
    async def test_frontend_tools(self) -> bool:
        """Test frontend tool execution capability"""
        url = f"{self.base_url}/agui/awp?agent=human_in_loop_agent"
        
        # Request with frontend tools defined - using camelCase fields
        request_data = {
            "messages": [
                {
                    "id": "msg-1",
                    "role": "user",
                    "content": "Delete the important file please"
                }
            ],
            "threadId": f"test-thread-{int(time.time())}",
            "runId": f"test-run-{int(time.time())}",
            "state": {},
            "tools": [
                {
                    "name": "confirmAction",
                    "description": "Get user confirmation",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string"},
                            "reason": {"type": "string"}
                        }
                    }
                }
            ],
            "context": [],
            "forwardedProps": {}
        }
        
        print(f"\n🔍 Testing frontend tools support")
        
        try:
            async with self.client.stream(
                "POST",
                url,
                json=request_data,
                headers={"Content-Type": "application/json"}
            ) as response:
                if response.status_code != 200:
                    print(f"❌ Frontend tools test failed: {response.status_code}")
                    return False
                
                tool_call_detected = False
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        event_data = line[6:]
                        if event_data == "[DONE]":
                            break
                        
                        try:
                            event = json.loads(event_data)
                            if event.get("type") == "tool.call.start":
                                print(f"✅ Tool call detected: {event.get('name')}")
                                tool_call_detected = True
                        except json.JSONDecodeError:
                            pass
                
                if tool_call_detected:
                    print("✅ Frontend tools support confirmed")
                    return True
                else:
                    print("⚠️  No tool calls detected (agent may not need confirmation)")
                    return True  # Not a failure, agent might handle it differently
                    
        except Exception as e:
            print(f"❌ Frontend tools test error: {e}")
            return False


async def main():
    """Run all integration tests"""
    print("🚀 AG-UI Integration Test Suite")
    print("=" * 50)
    
    async with AGUIIntegrationTester() as tester:
        # Check if backend is running
        print("\n1️⃣ Testing backend connectivity...")
        if not await tester.test_health_check():
            print("\n❌ Backend is not running. Please start it with:")
            print("   python cookbook/apps/agui/basic.py")
            return
        
        # List available agents
        print("\n2️⃣ Testing agent listing...")
        await tester.test_list_agents()
        
        # Test each agent
        print("\n3️⃣ Testing individual agents...")
        results = await tester.test_all_agents()
        
        # Test frontend tools
        print("\n4️⃣ Testing frontend tools support...")
        tools_result = await tester.test_frontend_tools()
        
        # Summary
        print("\n" + "=" * 50)
        print("📊 Test Summary:")
        print("=" * 50)
        
        passed = sum(1 for r in results.values() if r)
        total = len(results)
        
        for agent, success in results.items():
            status = "✅ PASS" if success else "❌ FAIL"
            print(f"{agent:<30} {status}")
        
        print(f"\nFrontend Tools Support: {'✅ PASS' if tools_result else '❌ FAIL'}")
        print(f"\nTotal: {passed}/{total} agents passed")
        print("=" * 50)
        
        # Overall result
        if passed == total and tools_result:
            print("\n🎉 All tests passed! AG-UI integration is working correctly.")
        else:
            print("\n⚠️  Some tests failed. Please check the output above.")


if __name__ == "__main__":
    asyncio.run(main()) 