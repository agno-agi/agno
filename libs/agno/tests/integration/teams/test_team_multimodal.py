from agno.agent.agent import Agent
from agno.media import Image
from agno.models.openai.chat import OpenAIChat
from agno.team.team import Team


def test_team_image_input(team_storage, agent_storage):
    image_analyst = Agent(
        name="Image Analyst",
        role="Analyze images and provide insights.",
        model=OpenAIChat(id="gpt-4o-mini"),
        markdown=True,
        storage=agent_storage,
    )

    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[image_analyst],
        name="Team",
        storage=team_storage,
    )

    response = team.run(
        "Tell me about this image and give me the latest news about it.",
        images=[Image(url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg")],
    )
    assert response.content is not None

    session_in_db = team_storage.read(response.session_id)
    assert session_in_db is not None
    assert session_in_db.memory["runs"] is not None
    assert len(session_in_db.memory["runs"]) == 1
    assert session_in_db.memory["runs"][0]["messages"] is not None
    assert session_in_db.memory["runs"][0]["messages"][1]["role"] == "user"
    assert session_in_db.memory["runs"][0]["messages"][1]["images"] is not None
    assert (
        session_in_db.memory["runs"][0]["messages"][1]["images"][0]["url"]
        == "https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg"
    )


def test_team_image_input_no_prompt(team_storage, agent_storage):
    image_analyst = Agent(
        name="Image Analyst",
        role="Analyze images and provide insights.",
        model=OpenAIChat(id="gpt-4o-mini"),
        markdown=True,
        storage=agent_storage,
    )

    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[image_analyst],
        name="Team",
        storage=team_storage,
    )

    response = team.run(
        images=[Image(url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg")],
        message="Analyze this image and provide insights.",
    )
    assert response.content is not None

    session_in_db = team_storage.read(response.session_id)
    assert session_in_db is not None
    assert session_in_db.memory["runs"] is not None
    assert len(session_in_db.memory["runs"]) == 1
    assert session_in_db.memory["runs"][0]["messages"] is not None
    assert session_in_db.memory["runs"][0]["messages"][1]["role"] == "user"
    assert session_in_db.memory["runs"][0]["messages"][1]["images"] is not None
    assert (
        session_in_db.memory["runs"][0]["messages"][1]["images"][0]["url"]
        == "https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg"
    )
