"""
This recipe shows how to store agent sessions in a MongoDB database.
Steps:
1. Run: `pip install openai google-cloud-firestore agno` to install dependencies
2. Make sure your gcloud project is set up and you have the necessary permissions to access Firestore
3. Run: `python cookbook/memory/09_persistent_memory_firestore.py` to run the agent
"""

import json

from agno.agent import Agent
from agno.memory.agent import AgentMemory
from agno.memory.db.firestore import FirestoreMemoryDb
from agno.models.openai import OpenAIChat
from agno.storage.agent.firestore import FirestoreAgentStorage

from rich.console import Console
from rich.json import JSON
from rich.panel import Panel

# The only required argument is the collection name.
# Firestore will connect automatically using your google cloud credentials.
# If you don't specificy a db_name, the class uses the (default) database by default to allow free tier access to firestore.
# You can specify a project_id if you'd like to connect to firestore in a different GCP project

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    # Store agent sessions in Firestore
    storage=FirestoreAgentStorage(
        collection_name="agent_sessions",
    ),
    # Store memories in Firestore
    memory=AgentMemory(
        db=FirestoreMemoryDb(),
        create_user_memories=True,
        create_session_summary=True,
    ),
    # Set add_history_to_messages=true to add the previous chat history to the messages sent to the Model.
    add_history_to_messages=True,
    # Number of historical responses to add to the messages.
    num_history_responses=3,
    # The session_id is used to identify the session in the database
    # You can resume any session by providing a session_id
    # session_id="xxxx-xxxx-xxxx-xxxx",
    # Description creates a system prompt for the agent
    description="You are a helpful assistant that always responds in a polite, upbeat and positive manner.",
)

console = Console()


def print_chat_history(agent):
    # -*- Print history
    console.print(
        Panel(
            JSON(
                json.dumps(
                    [
                        m.model_dump(include={"role", "content"})
                        for m in agent.memory.messages
                    ]
                ),
                indent=4,
            ),
            title=f"Chat History for session_id: {agent.session_id}",
            expand=True,
        )
    )


# -*- Create a run
agent.print_response("Share a 2 sentence horror story", stream=True)
# -*- Print the chat history
print_chat_history(agent)

# -*- Ask a follow up question that continues the conversation
agent.print_response("What was my first message?", stream=True)
# -*- Print the chat history
print_chat_history(agent)
