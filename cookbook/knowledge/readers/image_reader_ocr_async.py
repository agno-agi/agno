"""
Async example: Add image content using OCR reader.
Run: `python 01_add_ocr_content_async.py`
"""

import asyncio
from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.image_reader import ImageProcessingMode, ImageReader
from agno.vectordb.lancedb import LanceDb
from agno.utils.log import set_log_level_to_debug
import dotenv

dotenv.load_dotenv()
set_log_level_to_debug()

async def main():
    # Initialize vector database for OCR
    vector_db_ocr = LanceDb(
        table_name="recipes_ocr",
        uri="tmp/lancedb_ocr",
    )

    # OCR Reader setup
    ocr_reader = ImageReader(
        mode=ImageProcessingMode.OCR,
    )

    # Create Knowledge instance
    knowledge_ocr = Knowledge(
        name="OCR Knowledge Base",
        description="Knowledge added via OCR reader",
        vector_db=vector_db_ocr,
    )

    # Add content using OCR reader asynchronously
    await knowledge_ocr.add_content(
        path="cookbook/knowledge/testing_resources/images/",
        metadata={"user_tag": "Engineering Candidates - OCR"},
        reader=ocr_reader,
        skip_if_exists=False
    )

    # Create Agent
    agent_ocr = Agent(
        knowledge=knowledge_ocr,
        search_knowledge=True,
    )

    # Query knowledge base asynchronously
    print("=== OCR Reader Async Example ===")
    await agent_ocr.aprint_response("What is in these images?", markdown=True)

if __name__ == "__main__":
    asyncio.run(main())
