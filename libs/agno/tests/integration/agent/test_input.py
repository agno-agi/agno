from pydantic import BaseModel

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media import Image
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.session.summary import SessionSummaryManager


def test_message_as_input():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        markdown=True,
    )

    response = agent.run(input=Message(role="user", content="Hello, how are you?"))
    assert response.content is not None


def test_list_as_input(image_path):
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        markdown=True,
    )

    response = agent.run(
        input=[
            {"type": "text", "text": "What's in this image?"},
            {
                "type": "image_url",
                "image_url": {
                    "url": image_path,
                },
            },
        ]
    )
    assert response.content is not None


def test_dict_as_input():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        markdown=True,
    )

    response = agent.run(
        input={
            "role": "user",
            "content": "Hello, how are you?",
        }
    )
    assert response.content is not None


def test_base_model_as_input():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        markdown=True,
    )

    class InputMessage(BaseModel):
        topic: str
        content: str

    response = agent.run(input=InputMessage(topic="Greetings", content="Hello, how are you?"))
    assert response.content is not None


def test_empty_string_with_image(image_path):
    """Test that agent handles empty string input with image media"""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="Describe the image provided",
        markdown=True,
    )

    response = agent.run(
        input="",
        images=[Image(filepath=image_path)],
    )
    assert response.content is not None
    assert len(response.content) > 0


def test_none_input_with_image(image_path):
    """Test that agent handles None input with image media"""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="Describe the image provided",
        markdown=True,
    )

    response = agent.run(
        input=None,  # type: ignore
        images=[Image(filepath=image_path)],
    )
    assert response.content is not None
    assert len(response.content) > 0


def test_empty_string_with_multiple_media(image_path):
    """Test that agent handles empty string with multiple media types"""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="Analyze the provided media",
        markdown=True,
    )

    response = agent.run(
        input="",
        images=[Image(filepath=image_path)],
    )
    assert response.content is not None
    assert len(response.content) > 0


def test_empty_string_with_image_and_user_memories(image_path):
    """Test that agent with user memories handles empty string input with image"""
    db = SqliteDb(db_file="tmp/test_empty_input_memories.db")
    session_summary_manager = SessionSummaryManager(model=OpenAIChat(id="gpt-4o-mini"))

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="Describe the image provided",
        db=db,
        update_memory_on_run=True,
        session_summary_manager=session_summary_manager,
        markdown=True,
    )

    response = agent.run(
        input="",
        images=[Image(filepath=image_path)],
    )
    assert response.content is not None
    assert len(response.content) > 0


def test_none_input_with_image_and_user_memories(image_path):
    """Test that agent with user memories handles None input with image"""
    db = SqliteDb(db_file="tmp/test_none_input_memories.db")
    session_summary_manager = SessionSummaryManager(model=OpenAIChat(id="gpt-4o-mini"))

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="Describe the image provided",
        db=db,
        update_memory_on_run=True,
        session_summary_manager=session_summary_manager,
        markdown=True,
    )

    response = agent.run(
        input=None,  # type: ignore
        images=[Image(filepath=image_path)],
    )
    assert response.content is not None
    assert len(response.content) > 0


def test_empty_string_with_image_and_session_summaries(image_path):
    """Test that agent with session summaries handles empty string input with image"""
    db = SqliteDb(db_file="tmp/test_empty_input_summaries.db")
    session_summary_manager = SessionSummaryManager(model=OpenAIChat(id="gpt-4o-mini"))

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="Describe the image provided",
        db=db,
        enable_session_summaries=True,
        session_summary_manager=session_summary_manager,
        markdown=True,
    )

    response = agent.run(
        input="",
        images=[Image(filepath=image_path)],
    )
    assert response.content is not None
    assert len(response.content) > 0


def test_none_input_with_image_and_session_summaries(image_path):
    """Test that agent with session summaries handles None input with image"""
    db = SqliteDb(db_file="tmp/test_none_input_summaries.db")
    session_summary_manager = SessionSummaryManager(model=OpenAIChat(id="gpt-4o-mini"))

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="Describe the image provided",
        db=db,
        enable_session_summaries=True,
        session_summary_manager=session_summary_manager,
        markdown=True,
    )

    response = agent.run(
        input=None,  # type: ignore
        images=[Image(filepath=image_path)],
    )
    assert response.content is not None
    assert len(response.content) > 0
