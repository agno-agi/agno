#!/usr/bin/env python3
"""
Test script to demonstrate the enhanced AgentOS auto-discovery functionality.

This script shows how AgentOS can automatically discover managers from agents, teams, and workflows
when no managers are explicitly passed to the constructor.
"""

from agno.agent import Agent
from agno.db.postgres.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.memory.memory import Memory
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team.team import Team
from agno.workflow.workflow import Workflow

# Setup database connection
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(
    db_url=db_url,
    agent_session_table="agent_sessions",
    team_session_table="team_sessions", 
    workflow_session_table="workflow_sessions",
    user_memory_table="user_memories",
    eval_table="eval_runs",
    metrics_table="metrics",
    knowledge_table="knowledge_documents",
)

# Setup memory
memory = Memory(db=db)

# Setup knowledge base
knowledge = Knowledge(
    name="Test Knowledge Base",
    description="A test knowledge base for auto-discovery",
    document_store=None,  # Simplified for demo
    documents_db=db,
    vector_store=None,  # Simplified for demo
)

# Create agents with different components
agent_with_memory = Agent(
    name="Memory Agent",
    model=OpenAIChat(id="gpt-4o"),
    memory=memory,
    enable_user_memories=True,
)

agent_with_knowledge = Agent(
    name="Knowledge Agent", 
    model=OpenAIChat(id="gpt-4o"),
    knowledge=knowledge,
)

# Create a team with memory
team = Team(
    name="Test Team",
    members=[agent_with_memory],
    memory=memory,
    enable_user_memories=True,
)

# Create a workflow with storage
workflow = Workflow(
    name="Test Workflow",
    storage=db,
    memory=memory,
)

def test_auto_discovery_with_agents():
    """Test auto-discovery with agents only."""
    print("\n=== Testing Auto-Discovery with Agents ===")
    
    agent_os = AgentOS(
        name="Agent Auto-Discovery Test",
        description="Testing auto-discovery with agents",
        os_id="agent-auto-discovery",
        agents=[agent_with_memory, agent_with_knowledge],
        # No managers passed - should auto-discover
    )
    
    print(f"Auto-discovered {len(agent_os.managers)} managers:")
    for manager in agent_os.managers:
        print(f"  - {manager.name} ({manager.type})")
    
    return agent_os

def test_auto_discovery_with_teams():
    """Test auto-discovery with teams only."""
    print("\n=== Testing Auto-Discovery with Teams ===")
    
    agent_os = AgentOS(
        name="Team Auto-Discovery Test", 
        description="Testing auto-discovery with teams",
        os_id="team-auto-discovery",
        teams=[team],
        # No managers passed - should auto-discover
    )
    
    print(f"Auto-discovered {len(agent_os.managers)} managers:")
    for manager in agent_os.managers:
        print(f"  - {manager.name} ({manager.type})")
    
    return agent_os

def test_auto_discovery_with_workflows():
    """Test auto-discovery with workflows only."""
    print("\n=== Testing Auto-Discovery with Workflows ===")
    
    agent_os = AgentOS(
        name="Workflow Auto-Discovery Test",
        description="Testing auto-discovery with workflows", 
        os_id="workflow-auto-discovery",
        workflows=[workflow],
        # No managers passed - should auto-discover
    )
    
    print(f"Auto-discovered {len(agent_os.managers)} managers:")
    for manager in agent_os.managers:
        print(f"  - {manager.name} ({manager.type})")
    
    return agent_os

def test_auto_discovery_with_mixed():
    """Test auto-discovery with mixed agents, teams, and workflows."""
    print("\n=== Testing Auto-Discovery with Mixed Components ===")
    
    agent_os = AgentOS(
        name="Mixed Auto-Discovery Test",
        description="Testing auto-discovery with mixed components",
        os_id="mixed-auto-discovery", 
        agents=[agent_with_memory, agent_with_knowledge],
        teams=[team],
        workflows=[workflow],
        # No managers passed - should auto-discover
    )
    
    print(f"Auto-discovered {len(agent_os.managers)} managers:")
    for manager in agent_os.managers:
        print(f"  - {manager.name} ({manager.type})")
    
    return agent_os

def test_explicit_managers_override():
    """Test that explicitly passed managers override auto-discovery."""
    print("\n=== Testing Explicit Managers Override ===")
    
    from agno.os.managers import SessionManager, MemoryManager
    
    # Create explicit managers
    explicit_session_manager = SessionManager(db=db, name="Explicit Session Manager")
    explicit_memory_manager = MemoryManager(memory=memory, name="Explicit Memory Manager")
    
    agent_os = AgentOS(
        name="Explicit Managers Test",
        description="Testing explicit managers override auto-discovery",
        os_id="explicit-managers",
        agents=[agent_with_memory, agent_with_knowledge],
        teams=[team],
        workflows=[workflow],
        managers=[explicit_session_manager, explicit_memory_manager],  # Explicit managers
    )
    
    print(f"Using {len(agent_os.managers)} explicit managers:")
    for manager in agent_os.managers:
        print(f"  - {manager.name} ({manager.type})")
    
    return agent_os

if __name__ == "__main__":
    print("AgentOS Auto-Discovery Enhancement Test")
    print("=" * 50)
    
    # Run all tests
    test_auto_discovery_with_agents()
    test_auto_discovery_with_teams() 
    test_auto_discovery_with_workflows()
    test_auto_discovery_with_mixed()
    test_explicit_managers_override()
    
    print("\n" + "=" * 50)
    print("Auto-discovery enhancement test completed!")
    print("\nKey Features Demonstrated:")
    print("1. Auto-discovery of managers from agents, teams, and workflows")
    print("2. Unique component detection to avoid duplicates")
    print("3. Descriptive manager names based on source component")
    print("4. Explicit managers override auto-discovery when provided")
    print("5. Support for Session, Knowledge, Memory, Metrics, and Eval managers") 