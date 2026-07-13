from pydantic import BaseModel

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media import Image
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.session.summary import SessionSummaryManager
from agno.team import Team


def test_message_as_input():
    researcher = Agent(
        name="Researcher",
        role="Research and provide information",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    writer = Agent(
        name="Writer",
        role="Write based on research",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        members=[researcher, writer],
        model=OpenAIChat(id="gpt-4o-mini"),
        markdown=True,
    )

    response = team.run(input=Message(role="user", content="Hello, how are you?"))
    assert response.content is not None


def test_list_as_input():
    researcher = Agent(
        name="Researcher",
        role="Research and provide information",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    writer = Agent(
        name="Writer",
        role="Write based on research",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        members=[researcher, writer],
        model=OpenAIChat(id="gpt-4o-mini"),
        markdown=True,
    )

    response = team.run(
        input=[
            {"type": "text", "text": "What's in this image?"},
            {
                "type": "image_url",
                "image_url": {
                    "url": "https://www.exp1.com/wp-content/uploads/sites/7/2018/08/Golden-Gate-Bridge.jpg",
                },
            },
        ]
    )
    assert response.content is not None


def test_dict_as_input():
    researcher = Agent(
        name="Researcher",
        role="Research and provide information",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    writer = Agent(
        name="Writer",
        role="Write based on research",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        members=[researcher, writer],
        model=OpenAIChat(id="gpt-4o-mini"),
        markdown=True,
    )

    response = team.run(
        input={
            "role": "user",
            "content": "Hello, how are you?",
        }
    )
    assert response.content is not None


def test_base_model_as_input():
    researcher = Agent(
        name="Researcher",
        role="Research and provide information",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    writer = Agent(
        name="Writer",
        role="Write based on research",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        members=[researcher, writer],
        model=OpenAIChat(id="gpt-4o-mini"),
        markdown=True,
    )

    class InputMessage(BaseModel):
        topic: str
        content: str

    response = team.run(input=InputMessage(topic="Greetings", content="Hello, how are you?"))
    assert response.content is not None


def test_empty_string_with_image():
    """Test that team handles empty string input with image media"""
    vision_agent = Agent(
        name="Vision Analyst",
        role="Analyze images",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    reporter = Agent(
        name="Reporter",
        role="Write reports",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        members=[vision_agent, reporter],
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="Describe the image provided",
        markdown=True,
    )

    response = team.run(
        input="",
        images=[Image(url="https://www.exp1.com/wp-content/uploads/sites/7/2018/08/Golden-Gate-Bridge.jpg")],
    )
    assert response.content is not None
    assert len(response.content) > 0


def test_none_input_with_image():
    """Test that team handles None input with image media"""
    vision_agent = Agent(
        name="Vision Analyst",
        role="Analyze images",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    reporter = Agent(
        name="Reporter",
        role="Write reports",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        members=[vision_agent, reporter],
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="Describe the image provided",
        markdown=True,
    )

    response = team.run(
        input=None,
        images=[Image(url="https://www.exp1.com/wp-content/uploads/sites/7/2018/08/Golden-Gate-Bridge.jpg")],
    )
    assert response.content is not None
    assert len(response.content) > 0


def test_empty_string_with_multiple_media():
    """Test that team handles empty string with multiple media types"""
    media_analyst = Agent(
        name="Media Analyst",
        role="Analyze media",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    writer = Agent(
        name="Content Writer",
        role="Write content",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        members=[media_analyst, writer],
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="Analyze the provided media",
        markdown=True,
    )

    response = team.run(
        input="",
        images=[Image(url="https://www.exp1.com/wp-content/uploads/sites/7/2018/08/Golden-Gate-Bridge.jpg")],
    )
    assert response.content is not None
    assert len(response.content) > 0


def test_empty_string_with_image_and_user_memories():
    """Test that team with user memories handles empty string input with image"""
    db = SqliteDb(db_file="tmp/test_team_empty_input_memories.db")
    session_summary_manager = SessionSummaryManager(model=OpenAIChat(id="gpt-4o-mini"))

    vision_agent = Agent(
        name="Vision Analyst",
        role="Analyze images",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    reporter = Agent(
        name="Reporter",
        role="Write reports",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        members=[vision_agent, reporter],
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="Describe the image provided",
        db=db,
        update_memory_on_run=True,
        session_summary_manager=session_summary_manager,
        markdown=True,
    )

    response = team.run(
        input="",
        images=[Image(url="https://www.exp1.com/wp-content/uploads/sites/7/2018/08/Golden-Gate-Bridge.jpg")],
    )
    assert response.content is not None
    assert len(response.content) > 0


def test_none_input_with_image_and_user_memories():
    """Test that team with user memories handles None input with image"""
    db = SqliteDb(db_file="tmp/test_team_none_input_memories.db")
    session_summary_manager = SessionSummaryManager(model=OpenAIChat(id="gpt-4o-mini"))

    vision_agent = Agent(
        name="Vision Analyst",
        role="Analyze images",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    reporter = Agent(
        name="Reporter",
        role="Write reports",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        members=[vision_agent, reporter],
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="Describe the image provided",
        db=db,
        update_memory_on_run=True,
        session_summary_manager=session_summary_manager,
        markdown=True,
    )

    response = team.run(
        input=None,
        images=[Image(url="https://www.exp1.com/wp-content/uploads/sites/7/2018/08/Golden-Gate-Bridge.jpg")],
    )
    assert response.content is not None
    assert len(response.content) > 0


def test_empty_string_with_image_and_session_summaries():
    """Test that team with session summaries handles empty string input with image"""
    db = SqliteDb(db_file="tmp/test_team_empty_input_summaries.db")
    session_summary_manager = SessionSummaryManager(model=OpenAIChat(id="gpt-4o-mini"))

    vision_agent = Agent(
        name="Vision Analyst",
        role="Analyze images",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    reporter = Agent(
        name="Reporter",
        role="Write reports",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        members=[vision_agent, reporter],
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="Describe the image provided",
        db=db,
        enable_session_summaries=True,
        session_summary_manager=session_summary_manager,
        markdown=True,
    )

    response = team.run(
        input="",
        images=[Image(url="https://www.exp1.com/wp-content/uploads/sites/7/2018/08/Golden-Gate-Bridge.jpg")],
    )
    assert response.content is not None
    assert len(response.content) > 0


def test_none_input_with_image_and_session_summaries():
    """Test that team with session summaries handles None input with image"""
    db = SqliteDb(db_file="tmp/test_team_none_input_summaries.db")
    session_summary_manager = SessionSummaryManager(model=OpenAIChat(id="gpt-4o-mini"))

    vision_agent = Agent(
        name="Vision Analyst",
        role="Analyze images",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    reporter = Agent(
        name="Reporter",
        role="Write reports",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        members=[vision_agent, reporter],
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="Describe the image provided",
        db=db,
        enable_session_summaries=True,
        session_summary_manager=session_summary_manager,
        markdown=True,
    )

    response = team.run(
        input=None,
        images=[Image(url="https://www.exp1.com/wp-content/uploads/sites/7/2018/08/Golden-Gate-Bridge.jpg")],
    )
    assert response.content is not None
    assert len(response.content) > 0
