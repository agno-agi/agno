#!/usr/bin/env python3
"""
Example demonstrating dynamic agent/workflow addition to AgentOS at runtime.

This example shows how to:
1. Create an AgentOS instance
2. Add agents, teams, and workflows dynamically at runtime
3. Use the new runtime management API endpoints
4. Monitor runtime statistics

Author: AgentOS Team
"""

import asyncio
import json
from typing import Dict, Any

from agno.agent.agent import Agent
from agno.team.team import Team
from agno.workflow.workflow import Workflow
from agno.os.app import AgentOS
from agno.db.postgres import PostgresDB
from agno.models.openai import OpenAIChat


def create_sample_agent(agent_id: str, name: str) -> Agent:
    """Create a sample agent for demonstration"""
    return Agent(
        id=agent_id,
        name=name,
        description=f"A sample agent: {name}",
        model=OpenAIChat(model="gpt-4"),
        # Add additional configuration as needed
    )


def create_sample_team(team_id: str, name: str, agents: list[Agent]) -> Team:
    """Create a sample team for demonstration"""
    return Team(
        id=team_id,
        name=name,
        description=f"A sample team: {name}",
        members=agents,
        model=OpenAIChat(model="gpt-4"),
    )


def create_sample_workflow(workflow_id: str, name: str) -> Workflow:
    """Create a sample workflow for demonstration"""
    return Workflow(
        id=workflow_id,
        name=name,
        description=f"A sample workflow: {name}",
        # Add workflow steps and configuration as needed
    )


def demonstration_basic_usage():
    """Demonstrate basic usage of dynamic runtime management"""
    print("=== AgentOS Dynamic Runtime Management Demo ===\n")
    
    # 1. Create initial AgentOS with minimal setup
    initial_agent = create_sample_agent("initial-agent", "Initial Agent")
    
    agent_os = AgentOS(
        name="Dynamic AgentOS Demo",
        description="Demonstrating dynamic runtime management capabilities",
        agents=[initial_agent],
    )
    
    print(f"✓ Created AgentOS with initial agent: {initial_agent.id}")
    
    # 2. Get initial stats
    initial_stats = agent_os.get_runtime_stats()
    print(f"✓ Initial stats: {json.dumps(initial_stats, indent=2)}")
    
    # 3. Add agents dynamically
    print("\n--- Adding Agents Dynamically ---")
    
    new_agent_1 = create_sample_agent("dynamic-agent-1", "Dynamic Agent 1")
    new_agent_2 = create_sample_agent("dynamic-agent-2", "Dynamic Agent 2")
    
    success_1 = agent_os.add_agent(new_agent_1)
    success_2 = agent_os.add_agent(new_agent_2)
    
    print(f"✓ Added {new_agent_1.id}: {success_1}")
    print(f"✓ Added {new_agent_2.id}: {success_2}")
    
    # 4. Try to add duplicate (should fail)
    duplicate_agent = create_sample_agent("dynamic-agent-1", "Duplicate Agent")
    duplicate_result = agent_os.add_agent(duplicate_agent)
    print(f"✗ Attempted to add duplicate agent: {duplicate_result}")
    
    # 5. Add teams dynamically
    print("\n--- Adding Teams Dynamically ---")
    
    team_agents = [new_agent_1, new_agent_2]
    new_team = create_sample_team("dynamic-team-1", "Dynamic Team 1", team_agents)
    
    team_success = agent_os.add_team(new_team)
    print(f"✓ Added {new_team.id}: {team_success}")
    
    # 6. Add workflows dynamically
    print("\n--- Adding Workflows Dynamically ---")
    
    new_workflow = create_sample_workflow("dynamic-workflow-1", "Dynamic Workflow 1")
    workflow_success = agent_os.add_workflow(new_workflow)
    print(f"✓ Added {new_workflow.id}: {workflow_success}")
    
    # 7. Get updated stats
    print("\n--- Updated Statistics ---")
    updated_stats = agent_os.get_runtime_stats()
    print(f"✓ Updated stats: {json.dumps(updated_stats, indent=2)}")
    
    # 8. Remove components
    print("\n--- Removing Components ---")
    
    remove_agent_result = agent_os.remove_agent("dynamic-agent-2")
    remove_team_result = agent_os.remove_team("dynamic-team-1")
    remove_workflow_result = agent_os.remove_workflow("dynamic-workflow-1")
    
    print(f"✓ Removed agent: {remove_agent_result}")
    print(f"✓ Removed team: {remove_team_result}")
    print(f"✓ Removed workflow: {remove_workflow_result}")
    
    # 9. Final stats
    print("\n--- Final Statistics ---")
    final_stats = agent_os.get_runtime_stats()
    print(f"✓ Final stats: {json.dumps(final_stats, indent=2)}")
    
    print("\n=== Demo Complete ===")


async def demonstration_api_usage():
    """Demonstrate usage via API endpoints (requires running AgentOS server)"""
    import httpx
    
    print("=== API Usage Demo ===")
    print("Note: This requires a running AgentOS server with the new runtime management endpoints")
    
    base_url = "http://localhost:7777"
    
    async with httpx.AsyncClient() as client:
        try:
            # 1. Get initial stats
            stats_response = await client.get(f"{base_url}/runtime/stats")
            if stats_response.status_code == 200:
                print(f"✓ Initial stats: {stats_response.json()}")
            
            # 2. Add an agent via API
            agent_config = {
                "id": "api-agent-1",
                "name": "API Agent 1",
                "description": "Agent added via API"
            }
            
            add_response = await client.post(
                f"{base_url}/runtime/agents",
                data={"agent_config": json.dumps(agent_config)}
            )
            
            if add_response.status_code == 200:
                print(f"✓ Added agent via API: {add_response.json()}")
            else:
                print(f"✗ Failed to add agent: {add_response.status_code} {add_response.text}")
            
            # 3. Get updated stats
            updated_stats_response = await client.get(f"{base_url}/runtime/stats")
            if updated_stats_response.status_code == 200:
                print(f"✓ Updated stats: {updated_stats_response.json()}")
            
            # 4. Remove the agent
            remove_response = await client.delete(f"{base_url}/runtime/agents/api-agent-1")
            if remove_response.status_code == 200:
                print(f"✓ Removed agent via API: {remove_response.json()}")
            
        except httpx.ConnectError:
            print("✗ Could not connect to AgentOS server. Make sure it's running on http://localhost:7777")
        except Exception as e:
            print(f"✗ API demo failed: {e}")


def demonstration_thread_safety():
    """Demonstrate thread safety of runtime operations"""
    import threading
    import time
    
    print("\n=== Thread Safety Demo ===")
    
    # Create AgentOS with initial agent
    initial_agent = create_sample_agent("thread-test-initial", "Initial Agent")
    agent_os = AgentOS(
        name="Thread Safety Test",
        agents=[initial_agent],
    )
    
    def add_agents_worker(worker_id: int, num_agents: int):
        """Worker function to add agents concurrently"""
        for i in range(num_agents):
            agent_id = f"worker-{worker_id}-agent-{i}"
            agent = create_sample_agent(agent_id, f"Worker {worker_id} Agent {i}")
            result = agent_os.add_agent(agent)
            print(f"Worker {worker_id}: Added {agent_id} -> {result}")
            time.sleep(0.1)  # Small delay to simulate real work
    
    # Create multiple threads to add agents concurrently
    threads = []
    for worker_id in range(3):
        thread = threading.Thread(target=add_agents_worker, args=(worker_id, 3))
        threads.append(thread)
    
    print("Starting concurrent agent addition...")
    
    # Start all threads
    for thread in threads:
        thread.start()
    
    # Wait for all threads to complete
    for thread in threads:
        thread.join()
    
    # Check final stats
    final_stats = agent_os.get_runtime_stats()
    print(f"✓ Final thread safety test stats: {json.dumps(final_stats, indent=2)}")
    
    expected_total = 1 + (3 * 3)  # initial + (3 workers * 3 agents each)
    actual_total = final_stats["agents"]["count"]
    
    if actual_total == expected_total:
        print(f"✓ Thread safety test passed: {actual_total}/{expected_total} agents")
    else:
        print(f"✗ Thread safety test failed: {actual_total}/{expected_total} agents")


def main():
    """Main demonstration function"""
    print("AgentOS Dynamic Runtime Management Examples\n")
    
    # Run basic usage demo
    demonstration_basic_usage()
    
    # Run thread safety demo
    demonstration_thread_safety()
    
    # Note about API demo
    print("\n=== API Demo Information ===")
    print("To run the API demo:")
    print("1. Start your AgentOS server: python your_agentOS_app.py")
    print("2. Uncomment and run: asyncio.run(demonstration_api_usage())")
    print("\nAvailable API endpoints:")
    print("- POST /runtime/agents - Add agent")
    print("- DELETE /runtime/agents/{agent_id} - Remove agent")
    print("- POST /runtime/teams - Add team")
    print("- DELETE /runtime/teams/{team_id} - Remove team")
    print("- POST /runtime/workflows - Add workflow")
    print("- DELETE /runtime/workflows/{workflow_id} - Remove workflow")
    print("- POST /runtime/refresh - Refresh routes")
    print("- GET /runtime/stats - Get runtime statistics")


if __name__ == "__main__":
    main()
    
    # Uncomment to run API demo (requires running server)
    # asyncio.run(demonstration_api_usage())
