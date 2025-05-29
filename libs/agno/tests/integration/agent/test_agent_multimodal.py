from agno.agent.agent import Agent
from agno.media import Image
from agno.models.openai.chat import OpenAIChat


def test_agent_image_input(agent_storage):
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        markdown=True,
        storage=agent_storage,
    )

    response = agent.run(
        "Tell me about this image and give me the latest news about it.",
        images=[Image(url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg")],
    )
    assert response.content is not None

    session_in_db = agent_storage.read(response.session_id)
    assert session_in_db is not None
    assert session_in_db.memory["runs"] is not None
    assert len(session_in_db.memory["runs"]) == 1
    assert session_in_db.memory["runs"][0]["messages"] is not None
    assert len(session_in_db.memory["runs"][0]["messages"]) == 3
    assert session_in_db.memory["runs"][0]["messages"][1]["role"] == "user"
    assert session_in_db.memory["runs"][0]["messages"][2]["role"] == "assistant"
    assert session_in_db.memory["runs"][0]["messages"][1]["images"] is not None
    assert (
        session_in_db.memory["runs"][0]["messages"][1]["images"][0]["url"]
        == "https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg"
    )


def test_agent_image_input_no_prompt(agent_storage):
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        markdown=True,
        storage=agent_storage,
    )

    response = agent.run(
        images=[Image(url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg")],
    )
    assert response.content is not None

    session_in_db = agent_storage.read(response.session_id)
    assert session_in_db is not None
    assert session_in_db.memory["runs"] is not None
    assert len(session_in_db.memory["runs"]) == 1
    assert session_in_db.memory["runs"][0]["messages"] is not None
    assert len(session_in_db.memory["runs"][0]["messages"]) == 3
    assert session_in_db.memory["runs"][0]["messages"][1]["role"] == "user"
    assert session_in_db.memory["runs"][0]["messages"][2]["role"] == "assistant"
    assert session_in_db.memory["runs"][0]["messages"][1]["images"] is not None
    assert (
        session_in_db.memory["runs"][0]["messages"][1]["images"][0]["url"]
        == "https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg"
    )
