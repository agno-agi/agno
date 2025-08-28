"""
Create user memories with an Agent by providing a either text or a list of messages.
"""

from agno.db.postgres import PostgresDb
from agno.memory import MemoryManager
from agno.models.anthropic.claude import Claude
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from rich.pretty import pprint

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

memory_db = PostgresDb(db_url=db_url)

memory = MemoryManager(
    model=OpenAIChat(id="gpt-4o"),
    memory_capture_instructions="""\
                    Memories should only include details about the user's academic interests.
                    Only include which subjects they are interested in.
                    Ignore names, hobbies, and personal interests.
                    """,
    db=memory_db,
)

john_doe_id = "john_doe@example.com"

memory.create_user_memories(
    message="""\
My name is John Doe.

I enjoy hiking in the mountains on weekends,
reading science fiction novels before bed,
cooking new recipes from different cultures,
playing chess with friends.

I am interested to learn about the history of the universe and other astronomical topics.
""",
    user_id=john_doe_id,
)


memories = memory.get_user_memories(user_id=john_doe_id)
print("John Doe's memories:")
pprint(memories)


# Use default memory manager
memory = MemoryManager(model=Claude(id="claude-3-5-sonnet-latest"), db=memory_db)
jane_doe_id = "jane_doe@example.com"

# Send a history of messages and add memories
memory.create_user_memories(
    messages=[
        Message(role="user", content="Hi, how are you?"),
        Message(role="assistant", content="I'm good, thank you!"),
        Message(role="user", content="What are you capable of?"),
        Message(
            role="assistant",
            content="I can help you with your homework and answer questions about the universe.",
        ),
        Message(role="user", content="My name is Jane Doe"),
        Message(role="user", content="I like to play chess"),
        Message(
            role="user",
            content="Actually, forget that I like to play chess. I more enjoy playing table top games like dungeons and dragons",
        ),
        Message(
            role="user",
            content="I'm also interested in learning about the history of the universe and other astronomical topics.",
        ),
        Message(role="assistant", content="That is great!"),
        Message(
            role="user",
            content="I am really interested in physics. Tell me about quantum mechanics?",
        ),
    ],
    user_id=jane_doe_id,
)

memories = memory.get_user_memories(user_id=jane_doe_id)
print("Jane Doe's memories:")
pprint(memories)
