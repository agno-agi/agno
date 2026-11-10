from agno.agent.agent import Agent
from agno.media import Image
from agno.models.openai.chat import OpenAIChat
from agno.team.team import Team


def test_team_image_input(shared_db, image_path):
    image_analyst = Agent(
        name="Image Analyst",
        role="Analyze images and provide insights.",
        model=OpenAIChat(id="gpt-4o-mini"),
        markdown=True,
        db=shared_db,
    )

    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[image_analyst],
        name="Team",
        db=shared_db,
    )

    response = team.run(
        "Tell me about this image and give me the latest news about it.",
        images=[Image(filepath=image_path)],
    )
    assert response.content is not None

    session_in_db = team.get_session(session_id=team.session_id)
    assert session_in_db is not None
    assert session_in_db.runs is not None
    assert session_in_db.runs[-1].messages is not None
    assert session_in_db.runs[-1].messages[1].role == "user"
    assert session_in_db.runs[-1].messages[1].images is not None  # type: ignore


def test_team_image_input_no_prompt(shared_db, image_path):
    image_analyst = Agent(
        name="Image Analyst",
        role="Analyze images and provide insights.",
        model=OpenAIChat(id="gpt-4o-mini"),
        markdown=True,
        db=shared_db,
    )

    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[image_analyst],
        name="Team",
        db=shared_db,
    )

    response = team.run(
        images=[Image(filepath=image_path)],
        input="Analyze this image and provide insights.",
    )
    assert response.content is not None

    session_in_db = team.get_session(session_id=team.session_id)
    assert session_in_db is not None
    assert session_in_db.runs is not None
    assert session_in_db.runs[-1].messages is not None
    assert session_in_db.runs[-1].messages[1].role == "user"
    assert session_in_db.runs[-1].messages[1].images is not None
