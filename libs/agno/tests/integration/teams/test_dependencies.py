import json

from agno.agent import RunOutput
from agno.db.in_memory import InMemoryDb
from agno.models.openai.chat import OpenAIChat
from agno.team import Team


def test_dependencies():
    team = Team(
        members=[],
        model=OpenAIChat(id="gpt-4o-mini"),
        dependencies={"robot_name": "Anna"},
        instructions="If you are asked to write a story about a robot, always name the robot {robot_name}",
    )

    # Run agent and return the response as a variable
    response: RunOutput = team.run("Tell me a 5 second short story about a robot named {robot_name}")

    # Check the system message
    assert "If you are asked to write a story about a robot, always name the robot Anna" in response.messages[0].content
    # Check the user message
    assert "Tell me a 5 second short story about a robot named Anna" in response.messages[1].content


def test_dependencies_function():
    def get_robot_name():
        return "Anna"

    team = Team(
        members=[],
        model=OpenAIChat(id="gpt-4o-mini"),
        dependencies={"robot_name": get_robot_name},
        instructions="If you are asked to write a story about a robot, always name the robot {robot_name}",
    )

    # Run agent and return the response as a variable
    response: RunOutput = team.run("Tell me a 5 second short story about a robot named {robot_name}")

    # Check the system message
    assert "If you are asked to write a story about a robot, always name the robot Anna" in response.messages[0].content
    # Check the user message
    assert "Tell me a 5 second short story about a robot named Anna" in response.messages[1].content


async def test_dependencies_async():
    team = Team(
        members=[],
        model=OpenAIChat(id="gpt-4o-mini"),
        dependencies={"robot_name": "Anna"},
        instructions="If you are asked to write a story about a robot, always name the robot {robot_name}",
    )

    # Run agent and return the response as a variable
    response: RunOutput = await team.arun("Tell me a 5 second short story about a robot named {robot_name}")

    # Check the system message
    assert "If you are asked to write a story about a robot, always name the robot Anna" in response.messages[0].content
    # Check the user message
    assert "Tell me a 5 second short story about a robot named Anna" in response.messages[1].content


async def test_dependencies_function_async():
    async def get_robot_name():
        return "Anna"

    team = Team(
        members=[],
        model=OpenAIChat(id="gpt-4o-mini"),
        dependencies={"robot_name": get_robot_name},
        instructions="If you are asked to write a story about a robot, always name the robot {robot_name}",
    )

    # Run agent and return the response as a variable
    response: RunOutput = await team.arun("Tell me a 5 second short story about a robot named {robot_name}")

    # Check the system message
    assert "If you are asked to write a story about a robot, always name the robot Anna" in response.messages[0].content
    # Check the user message
    assert "Tell me a 5 second short story about a robot named Anna" in response.messages[1].content


def test_dependencies_on_run():
    team = Team(
        members=[],
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="If you are asked to write a story about a robot, always name the robot {robot_name}",
    )

    # Run agent and return the response as a variable
    response: RunOutput = team.run(
        "Tell me a 5 second short story about a robot named {robot_name}",
        dependencies={"robot_name": "Anna"},
    )

    # Check the system message
    assert "If you are asked to write a story about a robot, always name the robot Anna" in response.messages[0].content
    # Check the user message
    assert "Tell me a 5 second short story about a robot named Anna" in response.messages[1].content


async def test_dependencies_on_run_async():
    team = Team(
        members=[],
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="If you are asked to write a story about a robot, always name the robot {robot_name}",
    )

    # Run agent and return the response as a variable
    response: RunOutput = await team.arun(
        "Tell me a 5 second short story about a robot named {robot_name}",
        dependencies={"robot_name": "Anna"},
    )

    # Check the system message
    assert "If you are asked to write a story about a robot, always name the robot Anna" in response.messages[0].content
    # Check the user message
    assert "Tell me a 5 second short story about a robot named Anna" in response.messages[1].content


def test_dependencies_mixed():
    team = Team(
        members=[],
        model=OpenAIChat(id="gpt-4o-mini"),
        dependencies={"robot_name": "Johnny"},
        instructions="If you are asked to write a story about a robot, always name the robot {robot_name}",
    )

    # Run agent and return the response as a variable
    response: RunOutput = team.run(
        "Tell me a 5 second short story about a robot named {robot_name}", dependencies={"robot_name": "Anna"}
    )

    # Check the system message
    assert "If you are asked to write a story about a robot, always name the robot Anna" in response.messages[0].content
    # Check the user message
    assert "Tell me a 5 second short story about a robot named Anna" in response.messages[1].content


async def test_dependencies_mixed_async():
    team = Team(
        members=[],
        model=OpenAIChat(id="gpt-4o-mini"),
        dependencies={"robot_name": "Johnny"},
        instructions="If you are asked to write a story about a robot, always name the robot {robot_name}",
    )

    # Run agent and return the response as a variable
    response: RunOutput = await team.arun(
        "Tell me a 5 second short story about a robot named {robot_name}", dependencies={"robot_name": "Anna"}
    )

    # Check the system message
    assert "If you are asked to write a story about a robot, always name the robot Anna" in response.messages[0].content
    # Check the user message
    assert "Tell me a 5 second short story about a robot named Anna" in response.messages[1].content


async def test_dependencies_mixed_async_stream():
    team = Team(
        members=[],
        model=OpenAIChat(id="gpt-4o-mini"),
        db=InMemoryDb(),
        dependencies={"robot_name": "Johnny"},
        instructions="If you are asked to write a story about a robot, always name the robot {robot_name}",
    )

    # Run agent and return the response as a variable
    response = team.arun(
        "Tell me a 5 second short story about a robot named {robot_name}",
        dependencies={"robot_name": "Anna"},
        stream=True,
        stream_intermediate_steps=True,
    )
    async for _ in response:
        pass

    run_response = team.get_last_run_output()

    # Check the system message
    assert (
        "If you are asked to write a story about a robot, always name the robot Anna"
        in run_response.messages[0].content
    )
    # Check the user message
    assert "Tell me a 5 second short story about a robot named Anna" in run_response.messages[1].content


def test_dependencies_resolve_in_context_false():
    team = Team(
        members=[],
        model=OpenAIChat(id="gpt-4o-mini"),
        dependencies={"robot_name": "Johnny"},
        instructions="If you are asked to write a story about a robot, always name the robot {robot_name}",
        resolve_in_context=False,
    )

    # Run agent and return the response as a variable
    response: RunOutput = team.run("Tell me a 5 second short story about a robot named {robot_name}")

    # Check the system message
    assert (
        "If you are asked to write a story about a robot, always name the robot {robot_name}"
        in response.messages[0].content
    )
    # Check the user message
    assert "Tell me a 5 second short story about a robot named {robot_name}" in response.messages[1].content


def test_add_dependencies_to_context():
    team = Team(
        members=[],
        model=OpenAIChat(id="gpt-4o-mini"),
        dependencies={"robot_name": "Johnny"},
        add_dependencies_to_context=True,
        markdown=True,
    )

    # Run agent and return the response as a variable
    response: RunOutput = team.run("Tell me a 5 second short story about a robot and include their name in the story.")

    # Check the user message
    assert json.dumps({"robot_name": "Johnny"}, indent=2, default=str) in response.messages[1].content
    # Check the response
    assert "Johnny" in response.content


def test_add_dependencies_to_context_function():
    def get_robot_name():
        return "Johnny"

    team = Team(
        members=[],
        model=OpenAIChat(id="gpt-4o-mini"),
        dependencies={"robot_name": get_robot_name},
        add_dependencies_to_context=True,
        markdown=True,
    )

    # Run agent and return the response as a variable
    response: RunOutput = team.run("Tell me a 5 second short story about a robot and include their name in the story.")

    # Check the user message
    assert json.dumps({"robot_name": "Johnny"}, indent=2, default=str) in response.messages[1].content
    # Check the response
    assert "Johnny" in response.content
