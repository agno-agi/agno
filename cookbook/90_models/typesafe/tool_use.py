"""
Jev Tool Use
============

Demonstrates closed-set tool calling: Jev picks one tool and fills its arguments.

Jev cannot write free text, so it can only fill arguments whose values form a closed set:
a `Literal` or `Enum`, a `bool`, or a list of `Literal` values. One request picks the tool and
answers every argument question at once. An optional argument is only passed when the request
says something about it, so the function's own default stands otherwise.

The tool result is the answer: after the tool runs, Jev hands its output back as the run content.
A tool with a required free-text argument is refused with an error before any call is made.

When no tool fits, Jev fails the turn so that `fallback_models` can answer instead.

Requirements:
- `pip install typesafe-sdk openai` (Python 3.10+)
- export TYPESAFE_API_KEY="your_api_key"
- export OPENAI_API_KEY="your_api_key"   (for the fallback model)
"""

import json
from typing import List, Literal, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.models.typesafe import Jev

# ---------------------------------------------------------------------------
# Create Tools
# ---------------------------------------------------------------------------

Room = Literal["living room", "bedroom", "kitchen"]


def set_lights(room: Room, on: bool, color: Literal["warm", "cool"] = "warm") -> str:
    """Turn the lights in a room on or off.

    Args:
        room: the room whose lights change
        on: whether the lights should end up on
        color: the color temperature of the light
    """
    return f"{room} lights {'on' if on else 'off'} ({color})"


def set_thermostat(mode: Literal["heat", "cool", "off"]) -> str:
    """Set the thermostat of the house.

    Args:
        mode: heat warms the house, cool lowers the temperature, off turns the system off
    """
    return f"thermostat set to {mode}"


def lock_doors(rooms: Optional[List[Literal["front", "back", "garage"]]] = None) -> str:
    """Lock doors of the house.

    Args:
        rooms: the doors to lock; every door when not given
    """
    return f"locked: {', '.join(rooms) if rooms else 'all doors'}"


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Jev(),
    tools=[set_lights, set_thermostat, lock_doors],
    # Anything that is not a device command goes to a generative model
    fallback_models=[OpenAIResponses(id="gpt-5.6-luna")],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    for command in (
        "It is freezing in here",
        "Turn off the bedroom lights",
        "Make the living room bright and cool-toned",
        "Lock the front door and the garage",
        "What is a good name for a smart home?",
    ):
        run = agent.run(command)
        print(f'"{command}"')
        print("  ->", run.content)
        calls = [(t.tool_name, t.tool_args) for t in run.tools or []]
        if calls:
            print("  call:", json.dumps(calls))
        print()
