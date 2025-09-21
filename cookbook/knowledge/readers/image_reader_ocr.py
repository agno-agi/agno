"""
This example adds image content to the knowledge base using OCR reader.
Run: `python 01_add_ocr_content.py`
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

# Add content using OCR reader
knowledge_ocr.add_content(
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

# Query knowledge base
print("=== OCR Reader Example ===")
agent_ocr.aprint_response("What is in these images?", markdown=True)
