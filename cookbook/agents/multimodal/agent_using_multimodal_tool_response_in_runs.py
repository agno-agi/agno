
from pathlib import Path

from agno.agent import Agent
from agno.tools.dalle import DalleTools
from agno.utils.media import download_image 
from agno.db.sqlite import SqliteDb

# Create an Agent with the DALL-E tool
agent = Agent(tools=[DalleTools()], name="DALL-E Image Generator", add_history_to_context=True, db=SqliteDb(db_file="tmp/test.db"))

# Example 1: Generate a basic image with default settings
agent.print_response(
    "Generate an image of a Siamese white furry cat sitting on a couch?",
    markdown=True,
)

agent.print_response(
    "Which type of animal and the breed are we talking about?",
    markdown=True
)