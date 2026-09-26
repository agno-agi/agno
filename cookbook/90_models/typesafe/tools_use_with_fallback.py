"""
Jev Tool Use with Fallback
==========================

Classify a smart-home command, select one tool, and fill finite arguments.
These tools simulate device actions. Door selections use separate boolean
arguments so a single call can select multiple doors without an array argument.

When Jev returns its explicit no-tool decision, application code sends the
original request to a generative agent. Service failures do not trigger fallback.

Requires Python 3.10+, typesafe-sdk, openai, TYPESAFE_API_KEY, and OPENAI_API_KEY.
"""

import json
from typing import Literal

from rich.pretty import pprint

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.models.typesafe import Jev
from agno.run.agent import RunOutput
from agno.run.base import RunStatus


def set_lights(
    room: Literal["living room", "bedroom", "kitchen"],
    on: bool,
    color: Literal["warm", "cool"] = "warm",
) -> str:
    """Turn the lights in one room on or off.

    Args:
        room: The room whose lights change.
        on: Whether the lights should end up on.
        color: The color temperature of the light.
    """
    return f"{room} lights {'on' if on else 'off'} ({color})"


def set_thermostat(mode: Literal["heat", "cool", "off"]) -> str:
    """Set the thermostat: heat warms the house, cool lowers the temperature, off stops it."""
    return f"thermostat set to {mode}"


def lock_doors(front: bool = False, back: bool = False, garage: bool = False) -> str:
    """Lock the selected doors, or all doors when none are specified.

    Args:
        front: Whether the front door is specifically requested.
        back: Whether the back door is specifically requested.
        garage: Whether the garage door is specifically requested.
    """
    doors = [
        name
        for name, selected in (("front", front), ("back", back), ("garage", garage))
        if selected
    ]
    return f"locked: {', '.join(doors) if doors else 'all doors'}"


agent = Agent(
    model=Jev(mode="tools"),
    tools=[set_lights, set_thermostat, lock_doors],
    cache_session=True,
)
fallback_agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    cache_session=True,
    instructions="Answer general smart-home questions briefly. Device commands are handled separately.",
)


def respond_to_command(command: str) -> RunOutput:
    agent.print_response(command)
    response = agent.get_last_run_output()
    if response is None:
        raise RuntimeError("No command response was saved")
    if (
        response.status == RunStatus.completed
        and not response.tools
        and json.loads(response.content) == {"tool": None}
    ):
        fallback_agent.print_response(command)
        response = fallback_agent.get_last_run_output()
        if response is None:
            raise RuntimeError("No fallback response was saved")
    return response


if __name__ == "__main__":
    for command in (
        "It is freezing in here",
        "Turn off the bedroom lights",
        "Make the living room bright and cool-toned",
        "Lock the front door and the garage",
        "What is a good name for a smart home?",
    ):
        response = respond_to_command(command)
        if response.tools:
            pprint(
                [
                    {"tool": call.tool_name, "arguments": call.tool_args}
                    for call in response.tools
                ]
            )
