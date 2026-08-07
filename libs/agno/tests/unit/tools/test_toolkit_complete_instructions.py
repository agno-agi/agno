"""Toolkit instructions must survive the live toolkit gaining functions (#9405)."""

from agno.agent import Agent
from agno.agent._tools import parse_tools
from agno.models.openai import OpenAIChat
from agno.registry import Registry
from agno.tools.toolkit import Toolkit


def test_saved_toolkit_instructions_survive_toolkit_growth():
    def read_file(path: str) -> str:
        """Read a file."""
        return path

    def write_file(path: str, body: str) -> str:
        """Write a file."""
        return path

    files = Toolkit(
        name="files",
        tools=[read_file, write_file],
        instructions="Always read a file before you write it.",
        add_instructions=True,
    )
    model = OpenAIChat(id="gpt-4o-mini")
    registry = Registry(tools=[files], models=[model])

    stored = []
    for _name, function in files.get_functions().items():
        tool_dict = function.to_dict()
        tool_dict["toolkit"] = files.name
        tool_dict["toolkit_complete"] = True
        stored.append(tool_dict)

    def load_and_collect() -> list:
        agent = Agent(name="a", model=model, tools=registry.rehydrate_functions([dict(d) for d in stored]))
        parse_tools(agent=agent, tools=agent.tools, model=model)
        return agent._tool_instructions or []

    assert "Always read a file before you write it." in load_and_collect()

    def delete_file(path: str) -> str:
        """Delete a file."""
        return path

    files.register(delete_file)
    assert "Always read a file before you write it." in load_and_collect()
