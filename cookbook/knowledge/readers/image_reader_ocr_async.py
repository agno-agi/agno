import asyncio
from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.image_reader import ImageProcessingMode, ImageReader
from agno.vectordb.lancedb import LanceDb

# === OCR Example ===
vector_db_ocr = LanceDb(
    table_name="recipes",
    uri="tmp/lancedb",
)
ocr_reader = ImageReader(
    mode=ImageProcessingMode.OCR,
)
knowledge_ocr = Knowledge(
    name="OCR Knowledge Base",
    description="Knowledge added via OCR reader",
    vector_db=vector_db_ocr,
)
agent_ocr = Agent(knowledge=knowledge_ocr, search_knowledge=True, debug_mode=True)


if __name__ == "__main__":
    asyncio.run(
        knowledge_ocr.add_content_async(
            path="cookbook/knowledge/testing_resources/images/",
            metadata={"user_tag": "agno docs - OCR"},
            reader=ocr_reader,
            skip_if_exists=False,
        )
    )
    asyncio.run(
        agent_ocr.aprint_response(
            "what is agno?",
            markdown=True,
        )
    )
