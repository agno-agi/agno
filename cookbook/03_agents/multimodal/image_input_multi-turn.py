from agno.agent import Agent
from agno.db.in_memory.in_memory_db import InMemoryDb
from agno.media import Image
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=InMemoryDb(),
    add_history_to_context=True,
    markdown=True,
    store_media=True,
)

agent.print_response(
    "Write a 3 sentence fiction story about the image",
    images=[Image(url="https://fal.media/files/koala/Chls9L2ZnvuipUTEwlnJC.png")],
)

# This should refer to history
agent.print_response("What is the content of the previous image?")
