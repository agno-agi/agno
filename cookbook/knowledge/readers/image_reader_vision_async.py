"""
Async example: Add image content using Vision reader.
Run: `python 02_add_vision_content_async.py`
"""

import asyncio
from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.image_reader import ImageProcessingMode, ImageReader
from agno.vectordb.lancedb import LanceDb
from agno.models.openai.chat import OpenAIChat
from agno.utils.log import set_log_level_to_debug
import dotenv

dotenv.load_dotenv()
set_log_level_to_debug()

async def main():
    # Initialize vector database for Vision
    vector_db_vision = LanceDb(
        table_name="recipes_vision",
        uri="tmp/lancedb_vision",
    )

    # Vision Reader setup
    vision_reader = ImageReader(
        mode=ImageProcessingMode.VISION,
        vision_model=OpenAIChat(id="gpt-5-mini"),
        vision_prompt="Describe the image that I have shared with you."
    )

    # Create Knowledge instance
    knowledge_vision = Knowledge(
        name="Vision Knowledge Base",
        description="Knowledge added via Vision reader",
        vector_db=vector_db_vision,
    )

    # Add content using Vision reader asynchronously
    await knowledge_vision.add_content(
        path="cookbook/knowledge/testing_resources/images/",
        metadata={"user_tag": "Engineering Candidates - Vision"},
        reader=vision_reader,
        skip_if_exists=False
    )

    # Create Agent
    agent_vision = Agent(
        knowledge=knowledge_vision,
        search_knowledge=True,
    )

    # Query knowledge base asynchronously
    print("=== Vision Reader Async Example ===")
    await agent_vision.aprint_response("What is in these images?", markdown=True)

if __name__ == "__main__":
    asyncio.run(main())
