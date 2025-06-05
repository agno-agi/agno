"""
This example shows how to store agent sessions and memories in a Firestore database.

Key features demonstrated:
1. Persistent user memories stored in Firestore
2. Session summaries generated and stored
3. Multi-user support with isolated memories
4. Session persistence and resumption

Steps:
1. Ensure you have firestore enabled in your gcloud project. See: https://cloud.google.com/firestore/docs/create-database-server-client-library
2. Run: `pip install openai google-cloud-firestore agno` to install dependencies
3. Make sure your gcloud project is set up and you have the necessary permissions to access Firestore
"""

from agno.agent import Agent
from agno.memory.agent import AgentMemory
from agno.memory.db.firestore import FirestoreMemoryDb
from agno.models.openai import OpenAIChat
from agno.storage.firestore import FirestoreStorage
from rich.pretty import pprint

# Initialize Firestore components
# The only required argument is the collection name.
# Firestore will connect automatically using your google cloud credentials.
memory_db = FirestoreMemoryDb(collection_name="agno_memories")
agent_storage = FirestoreStorage(collection_name="agno_sessions")

# Define user IDs for demonstration
john_doe_id = "john.doe@example.com"
jane_smith_id = "jane.smith@example.com"

# Create agent with Firestore memory and storage
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    # Store agent sessions in Firestore for persistence
    storage=agent_storage,
    # Configure memory with Firestore backend
    memory=AgentMemory(
        db=memory_db,
        # Enable persistent user memories
        create_user_memories=True,
        # Enable session summaries
        create_session_summary=True,
        # Update memories after each run
        update_user_memories_after_run=True,
        update_session_summary_after_run=True,
    ),
    # Enable agent to manage memories
    enable_agentic_memory=True,
    # Add chat history to messages
    add_history_to_messages=True,
    num_history_runs=3,
    # Enable markdown formatting
    markdown=True,
    # Add memory references in responses
    add_memory_references=True,
    description="You are a helpful assistant with persistent memory across sessions.",
)

print("=== DEMO: Firestore Persistent Memory ===\n")

# --- Session 1: John Doe ---
print(f"--- Session 1: User {john_doe_id} ---")
session_1 = "session-john-1"

# First interaction - introduce user
agent.print_response(
    "My name is John Doe. I'm a software engineer working on AI projects. "
    "I love hiking and photography on weekends.",
    user_id=john_doe_id,
    session_id=session_1,
    stream=True
)

# Second interaction - test memory
agent.print_response(
    "What do you remember about me?",
    user_id=john_doe_id, 
    session_id=session_1,
    stream=True
)

# Show John's memories
print("\nJohn's Memories in Firestore:")
if agent.memory and agent.memory.memories:
    pprint([m.memory for m in agent.memory.memories])

# --- Session 2: Jane Smith (different user) ---
print(f"\n--- Session 2: User {jane_smith_id} ---")
session_2 = "session-jane-1"

# Jane's introduction
agent.print_response(
    "Hi! I'm Jane Smith. I'm a data scientist interested in machine learning. "
    "I enjoy reading sci-fi novels and playing chess.",
    user_id=jane_smith_id,
    session_id=session_2,
    stream=True
)

# Test that Jane doesn't see John's memories
agent.print_response(
    "What do you know about me?",
    user_id=jane_smith_id,
    session_id=session_2,
    stream=True
)

# Show Jane's memories (should be different from John's)
print("\nJane's Memories in Firestore:")
if agent.memory and agent.memory.memories:
    pprint([m.memory for m in agent.memory.memories])

# --- Session 3: Resume John's session (demonstrate persistence) ---
print(f"\n--- Session 3: Resuming {john_doe_id}'s conversation ---")
# Create a new session for John
session_3 = "session-john-2"

# The agent should remember John from the database
agent.print_response(
    "Do you remember who I am and what I told you about myself?",
    user_id=john_doe_id,
    session_id=session_3,
    stream=True
)

# Add more information
agent.print_response(
    "I forgot to mention - I also have a pet dog named Max who loves to join me on hikes.",
    user_id=john_doe_id,
    session_id=session_3,
    stream=True
)

# --- Show session summaries ---
print("\n=== Session Summaries ===")

# Get John's session summary
john_summary = agent.get_session_summary(session_id=session_1, user_id=john_doe_id)
if john_summary:
    print(f"\nJohn's Session 1 Summary:")
    pprint(john_summary)

# Get Jane's session summary  
jane_summary = agent.get_session_summary(session_id=session_2, user_id=jane_smith_id)
if jane_summary:
    print(f"\nJane's Session Summary:")
    pprint(jane_summary)

# --- Demonstrate direct memory access from Firestore ---
print("\n=== Direct Firestore Memory Access ===")

# Read all John's memories directly from Firestore
john_memories = memory_db.read_memories(user_id=john_doe_id, limit=10)
print(f"\nAll of John's memories from Firestore ({len(john_memories)} total):")
for mem in john_memories:
    pprint({"id": mem.id, "memory": mem.memory})

# Show that memories persist across agent instances
print("\n=== Creating new agent instance to verify persistence ===")
new_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    storage=agent_storage,
    memory=AgentMemory(
        db=memory_db,
        create_user_memories=True,
    ),
    user_id=john_doe_id,
)

# Load John's memories in the new agent
new_agent.memory.load_user_memories()
print(f"\nMemories loaded in new agent instance: {len(new_agent.memory.memories) if new_agent.memory.memories else 0}")

print("\n=== Firestore Collections Created ===")
print(f"- Memories: {memory_db.collection_name}")
print(f"- Sessions: {agent_storage.collection_name}")
print("\nCheck your Firestore console to see the persistent data!")
