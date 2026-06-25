"""Multi-turn conversation example with memory and context management"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.memory import MemoryManager
from agno.models.dashscope import DashScope

MODEL_ID = "qwen2.5-3b-instruct"
BASE_URL = "http://localhost:1234/v1"


def example_basic_multi_turn():
    """Basic multi-turn conversation without memory"""
    agent = Agent(
        model=DashScope(id=MODEL_ID, base_url=BASE_URL),
        markdown=True,
    )

    agent.print_response("My name is Alice and I love programming")
    agent.print_response("What did I just tell you about myself?")
    agent.print_response("What programming languages would you recommend for me?")


def example_with_memory():
    """Multi-turn conversation with persistent memory"""
    db = SqliteDb(db_file="tmp/agent_memory.db")
    memory_manager = MemoryManager(
        model=DashScope(id=MODEL_ID, base_url=BASE_URL),
        db=db,
    )

    agent = Agent(
        model=DashScope(id=MODEL_ID, base_url=BASE_URL),
        memory_manager=memory_manager,
        enable_agentic_memory=True,
        markdown=True,
    )

    user_id = "alice@example.com"

    agent.print_response(
        "I'm working on a machine learning project with Python",
        user_id=user_id,
    )
    agent.print_response(
        "What libraries should I use for my project?",
        user_id=user_id,
    )
    agent.print_response(
        "Can you help me optimize the training performance?",
        user_id=user_id,
    )


def example_with_session_id():
    """Multi-turn conversation with session management"""
    db = SqliteDb(db_file="tmp/agent_sessions.db")

    agent = Agent(
        model=DashScope(id=MODEL_ID, base_url=BASE_URL),
        db=db,
        session_id="user_123_session",
        add_history_to_context=True,
        markdown=True,
    )

    agent.print_response("I want to learn about quantum computing")
    agent.print_response("What are the prerequisites?")
    agent.print_response("How long will it take to learn?")


def example_with_storage():
    """Multi-turn conversation with persistent agent storage"""
    db = SqliteDb(db_file="tmp/agent_storage.db")

    agent = Agent(
        model=DashScope(id=MODEL_ID, base_url=BASE_URL),
        db=db,
        session_id="project_planning_session",
        add_history_to_context=True,
        num_history_runs=10,
        markdown=True,
    )

    agent.print_response("We need to build a REST API for our mobile app")
    agent.print_response("What tech stack would you recommend?")
    agent.print_response("How should we handle authentication?")
    agent.print_response("What about rate limiting?")


def example_local_deployment():
    """Multi-turn conversation with local Qwen model"""
    db = SqliteDb(db_file="tmp/local_memory.db")
    memory_manager = MemoryManager(
        model=DashScope(id=MODEL_ID, base_url=BASE_URL),
        db=db,
    )

    agent = Agent(
        model=DashScope(id=MODEL_ID, base_url=BASE_URL),
        memory_manager=memory_manager,
        enable_agentic_memory=True,
        markdown=True,
    )

    user_id = "dev@example.com"

    agent.print_response("Tell me about neural networks", user_id=user_id)
    agent.print_response(
        "How do they differ from traditional algorithms?", user_id=user_id
    )
    agent.print_response("Give me a simple example in Python", user_id=user_id)


if __name__ == "__main__":
    print("\n=== Example 1: Basic Multi-turn ===")
    example_basic_multi_turn()

    print("\n=== Example 2: With Memory ===")
    example_with_memory()

    print("\n=== Example 3: With Session ID ===")
    example_with_session_id()
