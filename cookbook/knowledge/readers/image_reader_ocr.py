from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.image_reader import ImageProcessingMode, ImageReader
from agno.vectordb.lancedb import LanceDb

# Initialize vector database for OCR
vector_db_ocr = LanceDb(
    table_name="recipes",
    uri="tmp/lancedb",
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
    metadata={"user_tag": "agno docs - OCR"},
    reader=ocr_reader,
    skip_if_exists=False,
)

# Create Agent
agent_ocr = Agent(knowledge=knowledge_ocr, search_knowledge=True, debug_mode=True)

agent_ocr.print_response("what is agno?", markdown=True)
