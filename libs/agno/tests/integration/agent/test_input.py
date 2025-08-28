from pydantic import BaseModel

from agno.agent import Agent
from agno.models.message import Message
from agno.models.openai import OpenAIChat


def test_message_as_input():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        markdown=True,
    )

    response = agent.run(input=Message(role="user", content="Hello, how are you?"))
    assert response.content is not None


def test_list_as_input():
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
                    "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/d/dd/Gfp-wisconsin-madison-the-nature-boardwalk.jpg/2560px-Gfp-wisconsin-madison-the-nature-boardwalk.jpg",
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
