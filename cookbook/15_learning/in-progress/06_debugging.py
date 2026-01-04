"""
Advanced: Debugging Learning
============================
Troubleshooting and inspecting learning operations.

When things don't work as expected:
1. Check if stores are initialized
2. Verify data is being saved
3. Inspect extracted content
4. Review tool calls

This cookbook provides debugging techniques.

Run:
    python cookbook/15_learning/advanced/06_debugging.py
"""

import json
from typing import Any

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, UserProfileConfig, LearningMode
from agno.models.openai import OpenAIResponses

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIResponses(id="gpt-5.2")

# ============================================================================
# Agent with Learning
# ============================================================================
agent = Agent(
    name="Debug Learning Agent",
    model=model,
    db=db,
    instructions="You remember things about users.",
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=UserProfileConfig(
            mode=LearningMode.AGENTIC,
            enable_agent_tools=True,
        ),
    ),
    markdown=True,
    # Enable debug mode
    debug_mode=True,
)


# ============================================================================
# Debug: Inspect Learning Machine State
# ============================================================================
def debug_learning_machine():
    """Inspect LearningMachine configuration and state."""
    print("=" * 60)
    print("Debug: LearningMachine State")
    print("=" * 60)

    learning = agent.learning

    print("\n--- Configuration ---")
    print(f"DB configured: {learning.db is not None}")
    print(f"Model configured: {learning.model is not None}")
    print(f"Knowledge configured: {learning.knowledge is not None}")

    print("\n--- Stores ---")
    for store_name, store in learning.stores.items():
        print(f"  {store_name}:")
        print(f"    - Type: {store.learning_type}")
        print(f"    - Schema: {store.schema.__name__ if hasattr(store.schema, '__name__') else store.schema}")
        print(f"    - Has tools: {len(store.get_tools()) > 0}")


# ============================================================================
# Debug: Inspect User Profile
# ============================================================================
def debug_user_profile(user_id: str):
    """Inspect a user's profile directly."""
    print("\n" + "=" * 60)
    print(f"Debug: User Profile for {user_id}")
    print("=" * 60)

    learning = agent.learning
    
    # Direct recall
    profile = learning.stores.get("user_profile")
    if profile:
        data = profile.recall(user_id=user_id)
        if data:
            print("\n--- Profile Data ---")
            print(f"Name: {data.name}")
            print(f"Preferred Name: {data.preferred_name}")
            print(f"Memories: {len(data.memories or [])} items")
            if data.memories:
                print("\n--- Memories ---")
                for i, mem in enumerate(data.memories, 1):
                    print(f"  {i}. {mem.get('content', mem)[:100]}...")
        else:
            print("\nNo profile found for this user.")
    else:
        print("\nUser profile store not configured.")


# ============================================================================
# Debug: Trace Tool Calls
# ============================================================================
def debug_tool_calls():
    """Show how to trace tool calls during interaction."""
    print("\n" + "=" * 60)
    print("Debug: Tracing Tool Calls")
    print("=" * 60)

    user = "debug_trace@example.com"

    print("\n--- Interaction with tool tracing ---\n")
    
    # Run with full response for inspection
    response = agent.run(
        "My name is Debug User. Please remember this.",
        user_id=user,
        session_id="debug_session",
        stream=False,
    )

    print(f"Response: {response.content[:200]}...")
    
    # Check for tool calls in response
    if hasattr(response, 'tool_calls') and response.tool_calls:
        print("\n--- Tool Calls Made ---")
        for tc in response.tool_calls:
            print(f"  Tool: {tc.name}")
            print(f"  Args: {tc.arguments}")
    else:
        print("\nNo tool calls in this response.")


# ============================================================================
# Debug: Check Context Injection
# ============================================================================
def debug_context_injection(user_id: str):
    """Check what context is being injected into the prompt."""
    print("\n" + "=" * 60)
    print("Debug: Context Injection")
    print("=" * 60)

    learning = agent.learning

    # Build context manually
    context = learning.build_context(
        user_id=user_id,
        session_id="debug_context_session",
        message="Test message",
    )

    print("\n--- Injected Context ---")
    if context:
        print(context[:2000])
        if len(context) > 2000:
            print(f"\n... ({len(context) - 2000} more characters)")
    else:
        print("No context injected (empty string)")


# ============================================================================
# Debug: Database Check
# ============================================================================
def debug_database():
    """Check database connectivity and tables."""
    print("\n" + "=" * 60)
    print("Debug: Database Check")
    print("=" * 60)

    print(f"\nDatabase URL: {db_url[:30]}...")
    
    try:
        # Try to query the database
        from sqlalchemy import create_engine, text
        engine = create_engine(db_url)
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            print("✅ Database connection successful")
            
            # Check for learning tables
            result = conn.execute(text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name LIKE '%agent%' OR table_name LIKE '%learn%' OR table_name LIKE '%memory%'
            """))
            tables = [row[0] for row in result]
            print(f"\nRelevant tables found: {tables or 'None'}")
    except Exception as e:
        print(f"❌ Database error: {e}")


# ============================================================================
# Debug: Common Issues
# ============================================================================
def debug_common_issues():
    """Print common issues and solutions."""
    print("\n" + "=" * 60)
    print("Common Issues and Solutions")
    print("=" * 60)
    print("""
┌─────────────────────────────────────────────────────────────┐
│ Issue: Memories not being saved                             │
├─────────────────────────────────────────────────────────────┤
│ Check:                                                      │
│ 1. Is the database configured? learning.db is not None     │
│ 2. Is the mode correct? BACKGROUND auto-saves, AGENTIC     │
│    requires tool calls                                      │
│ 3. Are enable_add_memory/enable_update_memory True?        │
│ 4. Is user_id being passed to agent.run()?                 │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ Issue: Context not appearing in responses                   │
├─────────────────────────────────────────────────────────────┤
│ Check:                                                      │
│ 1. Call debug_context_injection() to see injected context  │
│ 2. Verify profile/session has data via debug_user_profile()│
│ 3. Check extraction timing (AFTER vs BEFORE)               │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ Issue: Tools not working                                    │
├─────────────────────────────────────────────────────────────┤
│ Check:                                                      │
│ 1. Is enable_agent_tools=True?                             │
│ 2. Is the mode AGENTIC or PROPOSE?                         │
│ 3. Check learning.get_tools() returns tools                │
│ 4. Verify agent instructions mention the tools             │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ Issue: Namespace isolation not working                      │
├─────────────────────────────────────────────────────────────┤
│ Check:                                                      │
│ 1. Verify namespace parameter in config                    │
│ 2. If namespace="user", is user_id being passed?           │
│ 3. Check that different namespaces are actually different  │
└─────────────────────────────────────────────────────────────┘
""")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    debug_learning_machine()
    
    # Create some data first
    user = "debug_user@example.com"
    agent.print_response(
        "I'm a Python developer who loves FastAPI.",
        user_id=user,
        session_id="setup_debug",
        stream=True,
    )
    
    debug_user_profile(user)
    debug_tool_calls()
    debug_context_injection(user)
    debug_database()
    debug_common_issues()

    print("\n" + "=" * 60)
    print("✅ Use these debugging techniques to troubleshoot")
    print("   Enable debug_mode=True on agent for more output")
    print("=" * 60)
