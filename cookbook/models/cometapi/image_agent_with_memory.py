"""
Image analysis with memory example using CometAPI.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media import Image
from agno.models.cometapi import CometAPI

agent = Agent(
    model=CometAPI(id="gpt-4o"),  # GPT-4o has vision capabilities
    db=SqliteDb(db_file="tmp/cometapi_image_agent.db"),
    session_id="cometapi_image_session",
    markdown=True,
)

# First interaction with an image
agent.print_response(
    "Look at this image and remember what you see. Describe the character in detail.",
    images=[
        Image(
            url="https://httpbin.org/image/png"  # Reliable test image
        )
    ],
)

print("\n" + "=" * 50 + "\n")

# Follow-up question using memory
agent.print_response(
    "What was the main color of the character in the image I showed you earlier?"
)
