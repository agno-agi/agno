import asyncio
from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.image_reader import ImageProcessingMode, ImageReader
from agno.models.openai.chat import OpenAIChat
from agno.vectordb.lancedb import LanceDb

vector_db_vision = LanceDb(
    table_name="recipes",
    uri="tmp/lancedb",
)

vision_reader = ImageReader(
    mode=ImageProcessingMode.VISION,
    vision_model=OpenAIChat(id="gpt-5-mini"),
    vision_prompt="Describe the image that I have shared with you.",
)

knowledge_vision = Knowledge(
    name="Vision Knowledge Base",
    description="Knowledge added via Vision reader",
    vector_db=vector_db_vision,
)

agent_vision = Agent(knowledge=knowledge_vision, search_knowledge=True, debug_mode=True)

if __name__ == "__main__":
    asyncio.run(
        knowledge_vision.add_content_async(
            path="cookbook/knowledge/testing_resources/images/",
            metadata={"user_tag": "Engineering Candidates - Vision"},
            reader=vision_reader,
            skip_if_exists=False,
        )
    )
    asyncio.run(
        agent_vision.aprint_response(
            "what is agno?",
            markdown=True,
        )
    )
