import json

from agno.agent import Agent, RunOutput
from agno.db.in_memory import InMemoryDb
from agno.models.openai.chat import OpenAIChat
from agno.run.base import RunContext


def test_dependencies():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        dependencies={"robot_name": "Anna"},
        instructions="If you are asked to write a story about a robot, always name the robot {robot_name}",
    )

    # Run agent and return the response as a variable
    response: RunOutput = agent.run("Tell me a 5 second short story about a robot named {robot_name}")

    # Check the system message
    assert "If you are asked to write a story about a robot, always name the robot Anna" in response.messages[0].content
    # Check the user message
    assert "Tell me a 5 second short story about a robot named Anna" in response.messages[1].content


def test_dependencies_function():
    def get_robot_name():
        return "Anna"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        dependencies={"robot_name": get_robot_name},
        instructions="If you are asked to write a story about a robot, always name the robot {robot_name}",
    )

    # Run agent and return the response as a variable
    response: RunOutput = agent.run("Tell me a 5 second short story about a robot named {robot_name}")

    # Check the system message
    assert "If you are asked to write a story about a robot, always name the robot Anna" in response.messages[0].content
    # Check the user message
    assert "Tell me a 5 second short story about a robot named Anna" in response.messages[1].content


async def test_dependencies_async():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        dependencies={"robot_name": "Anna"},
        instructions="If you are asked to write a story about a robot, always name the robot {robot_name}",
    )

    # Run agent and return the response as a variable
    response: RunOutput = await agent.arun("Tell me a 5 second short story about a robot named {robot_name}")

    # Check the system message
    assert "If you are asked to write a story about a robot, always name the robot Anna" in response.messages[0].content
    # Check the user message
    assert "Tell me a 5 second short story about a robot named Anna" in response.messages[1].content


async def test_dependencies_function_async():
    async def get_robot_name():
        return "Anna"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        dependencies={"robot_name": get_robot_name},
        instructions="If you are asked to write a story about a robot, always name the robot {robot_name}",
    )

    # Run agent and return the response as a variable
    response: RunOutput = await agent.arun("Tell me a 5 second short story about a robot named {robot_name}")

    # Check the system message
    assert "If you are asked to write a story about a robot, always name the robot Anna" in response.messages[0].content
    # Check the user message
    assert "Tell me a 5 second short story about a robot named Anna" in response.messages[1].content


def test_dependencies_on_run():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="If you are asked to write a story about a robot, always name the robot {robot_name}",
    )

    # Run agent and return the response as a variable
    response: RunOutput = agent.run(
        "Tell me a 5 second short story about a robot named {robot_name}",
        dependencies={"robot_name": "Anna"},
    )

    # Check the system message
    assert "If you are asked to write a story about a robot, always name the robot Anna" in response.messages[0].content
    # Check the user message
    assert "Tell me a 5 second short story about a robot named Anna" in response.messages[1].content


async def test_dependencies_on_run_async():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="If you are asked to write a story about a robot, always name the robot {robot_name}",
    )

    # Run agent and return the response as a variable
    response: RunOutput = await agent.arun(
        "Tell me a 5 second short story about a robot named {robot_name}",
        dependencies={"robot_name": "Anna"},
    )

    # Check the system message
    assert "If you are asked to write a story about a robot, always name the robot Anna" in response.messages[0].content
    # Check the user message
    assert "Tell me a 5 second short story about a robot named Anna" in response.messages[1].content


def test_dependencies_mixed():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        dependencies={"robot_name": "Johnny"},
        instructions="If you are asked to write a story about a robot, always name the robot {robot_name}",
    )

    # Run agent and return the response as a variable
    response: RunOutput = agent.run(
        "Tell me a 5 second short story about a robot named {robot_name}", dependencies={"robot_name": "Anna"}
    )

    # Check the system message
    assert "If you are asked to write a story about a robot, always name the robot Anna" in response.messages[0].content
    # Check the user message
    assert "Tell me a 5 second short story about a robot named Anna" in response.messages[1].content


async def test_dependencies_mixed_async():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        dependencies={"robot_name": "Johnny"},
        instructions="If you are asked to write a story about a robot, always name the robot {robot_name}",
    )

    # Run agent and return the response as a variable
    response: RunOutput = await agent.arun(
        "Tell me a 5 second short story about a robot named {robot_name}", dependencies={"robot_name": "Anna"}
    )

    # Check the system message
    assert "If you are asked to write a story about a robot, always name the robot Anna" in response.messages[0].content
    # Check the user message
    assert "Tell me a 5 second short story about a robot named Anna" in response.messages[1].content


async def test_dependencies_mixed_async_stream():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=InMemoryDb(),
        dependencies={"robot_name": "Johnny"},
        instructions="If you are asked to write a story about a robot, always name the robot {robot_name}",
    )

    # Run agent and return the response as a variable
    response = agent.arun(
        "Tell me a 5 second short story about a robot named {robot_name}",
        dependencies={"robot_name": "Anna"},
        stream=True,
        stream_events=True,
    )
    async for _ in response:
        pass

    run_response = agent.get_last_run_output()

    # Check the system message
    assert (
        "If you are asked to write a story about a robot, always name the robot Anna"
        in run_response.messages[0].content
    )
    # Check the user message
    assert "Tell me a 5 second short story about a robot named Anna" in run_response.messages[1].content


def test_dependencies_resolve_in_context_false():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        dependencies={"robot_name": "Johnny"},
        instructions="If you are asked to write a story about a robot, always name the robot {robot_name}",
        resolve_in_context=False,
    )

    # Run agent and return the response as a variable
    response: RunOutput = agent.run("Tell me a 5 second short story about a robot named {robot_name}")

    # Check the system message
    assert (
        "If you are asked to write a story about a robot, always name the robot {robot_name}"
        in response.messages[0].content
    )
    # Check the user message
    assert "Tell me a 5 second short story about a robot named {robot_name}" in response.messages[1].content


def test_add_dependencies_to_context():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        dependencies={"robot_name": "Johnny"},
        add_dependencies_to_context=True,
        markdown=True,
    )

    # Run agent and return the response as a variable
    response: RunOutput = agent.run("Tell me a 5 second short story about a robot and include their name in the story.")

    # Check the user message
    assert json.dumps({"robot_name": "Johnny"}, indent=2, default=str) in response.messages[1].content
    # Check the response
    assert "Johnny" in response.content


def test_add_dependencies_to_context_function():
    def get_robot_name():
        return "Johnny"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        dependencies={"robot_name": get_robot_name},
        add_dependencies_to_context=True,
        markdown=True,
    )

    # Run agent and return the response as a variable
    response: RunOutput = agent.run("Tell me a 5 second short story about a robot and include their name in the story.")

    # Check the user message
    assert json.dumps({"robot_name": "Johnny"}, indent=2, default=str) in response.messages[1].content
    # Check the response
    assert "Johnny" in response.content


def test_dependencies_function_with_run_context():
    def get_robot_name(run_context: RunContext):
        return f"Anna-{run_context.run_id[:8]}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        dependencies={"robot_name": get_robot_name},
        instructions="If you are asked to write a story about a robot, always name the robot {robot_name}",
    )

    # Run agent and return the response as a variable
    response: RunOutput = agent.run("Tell me a 5 second short story about a robot named {robot_name}")

    # Verify run_id was used (robot name should contain part of run_id)
    assert response.run_id is not None
    robot_name_with_id = f"Anna-{response.run_id[:8]}"
    # Check the system message contains the resolved robot name
    assert (
        f"If you are asked to write a story about a robot, always name the robot {robot_name_with_id}"
        in response.messages[0].content
    )
    # Check the user message contains the resolved robot name
    assert f"Tell me a 5 second short story about a robot named {robot_name_with_id}" in response.messages[1].content


async def test_dependencies_function_with_run_context_async():
    async def get_robot_name(run_context: RunContext):
        return f"Anna-{run_context.run_id[:8]}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        dependencies={"robot_name": get_robot_name},
        instructions="If you are asked to write a story about a robot, always name the robot {robot_name}",
    )

    # Run agent and return the response as a variable
    response: RunOutput = await agent.arun("Tell me a 5 second short story about a robot named {robot_name}")

    # Verify run_id was used (robot name should contain part of run_id)
    assert response.run_id is not None
    robot_name_with_id = f"Anna-{response.run_id[:8]}"
    # Check the system message contains the resolved robot name
    assert (
        f"If you are asked to write a story about a robot, always name the robot {robot_name_with_id}"
        in response.messages[0].content
    )
    # Check the user message contains the resolved robot name
    assert f"Tell me a 5 second short story about a robot named {robot_name_with_id}" in response.messages[1].content


def test_dependencies_function_with_run_context_on_run():
    def get_robot_name(run_context: RunContext):
        return f"Anna-{run_context.run_id[:8]}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="If you are asked to write a story about a robot, always name the robot {robot_name}",
    )

    # Run agent and return the response as a variable
    response: RunOutput = agent.run(
        "Tell me a 5 second short story about a robot named {robot_name}",
        dependencies={"robot_name": get_robot_name},
    )

    # Verify run_id was used
    assert response.run_id is not None
    robot_name_with_id = f"Anna-{response.run_id[:8]}"
    # Check the system message contains the resolved robot name
    assert (
        f"If you are asked to write a story about a robot, always name the robot {robot_name_with_id}"
        in response.messages[0].content
    )
    # Check the user message contains the resolved robot name
    assert f"Tell me a 5 second short story about a robot named {robot_name_with_id}" in response.messages[1].content


async def test_dependencies_function_with_run_context_on_run_async():
    async def get_robot_name(run_context: RunContext):
        return f"Anna-{run_context.run_id[:8]}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="If you are asked to write a story about a robot, always name the robot {robot_name}",
    )

    # Run agent and return the response as a variable
    response: RunOutput = await agent.arun(
        "Tell me a 5 second short story about a robot named {robot_name}",
        dependencies={"robot_name": get_robot_name},
    )

    # Verify run_id was used
    assert response.run_id is not None
    robot_name_with_id = f"Anna-{response.run_id[:8]}"
    # Check the system message contains the resolved robot name
    assert (
        f"If you are asked to write a story about a robot, always name the robot {robot_name_with_id}"
        in response.messages[0].content
    )
    # Check the user message contains the resolved robot name
    assert f"Tell me a 5 second short story about a robot named {robot_name_with_id}" in response.messages[1].content
