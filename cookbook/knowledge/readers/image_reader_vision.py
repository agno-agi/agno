from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.image_reader import ImageProcessingMode, ImageReader
from agno.models.openai.chat import OpenAIChat
from agno.vectordb.lancedb import LanceDb

# Initialize vector database for Vision
vector_db_vision = LanceDb(
    table_name="recipes",
    uri="tmp/lancedb",
)

# Vision Reader setup
vision_reader = ImageReader(
    mode=ImageProcessingMode.VISION,
    vision_model=OpenAIChat(id="gpt-5-mini"),
    vision_prompt="Describe the image that I have shared with you.",
)

# Create Knowledge instance
knowledge_vision = Knowledge(
    name="Vision Knowledge Base",
    description="Knowledge added via Vision reader",
    vector_db=vector_db_vision,
)

# Add content using Vision reader
knowledge_vision.add_content(
    path="cookbook/knowledge/testing_resources/images/",
    metadata={"user_tag": "agno docs - Vision"},
    reader=vision_reader,
    skip_if_exists=False,
)

# Create Agent
agent_vision = Agent(knowledge=knowledge_vision, search_knowledge=True, debug_mode=True)


agent_vision.print_response("what is agno?", markdown=True)
