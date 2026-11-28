import json
from enum import Enum, IntEnum
from typing import Optional

import pytest
from pydantic import BaseModel

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.run import RunContext
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.team.team import Team
from agno.utils.prompts import get_json_output_prompt


class Priority(IntEnum):
    LOW = 1
    HIGH = 2


class Level(Enum):
    ONE = 1
    TWO = 2


class Code(Enum):
    TEXT = "text"
    NUMBER = 2


class Color(str, Enum):
    RED = "red"
    BLUE = "blue"


class Ticket(BaseModel):
    priority: Priority
    level: Level
    code: Code
    color: Color
    backup: Optional[Priority] = None


def _field_properties(prompt: str) -> dict:
    body = prompt.split("<json_field_properties>\n", 1)[1].split("\n</json_field_properties>", 1)[0]
    return json.loads(body)


def test_enum_defs_keep_the_pydantic_type():
    defs = _field_properties(get_json_output_prompt(Ticket))["$defs"]

    assert defs["Priority"] == {"type": "integer", "enum": [1, 2], "description": ""}
    assert defs["Level"] == {"type": "integer", "enum": [1, 2], "description": ""}
    assert defs["Code"] == {"enum": ["text", 2], "description": ""}


def test_string_enum_def_is_unchanged():
    prompt = get_json_output_prompt(Ticket)

    assert _field_properties(prompt)["$defs"]["Color"] == {
        "type": "string",
        "enum": ["red", "blue"],
        "description": "",
    }
    assert '"Color": {\n      "type": "string",\n      "enum": [' in prompt


def test_optional_enum_field_points_at_the_typed_def():
    properties = _field_properties(get_json_output_prompt(Ticket))

    assert {"$ref": "#/$defs/Priority"} in properties["backup"]["anyOf"]
    assert properties["$defs"]["Priority"]["type"] == "integer"


@pytest.mark.asyncio
async def test_agent_json_mode_system_message_describes_enums():
    agent = Agent(model=OpenAIResponses(id="gpt-5.6-luna"), output_schema=Ticket, use_json_mode=True)
    session = AgentSession(session_id="s1")
    run_context = RunContext(run_id="r1", session_id="s1", output_schema=Ticket)

    sync_message = agent.get_system_message(session=session, run_context=run_context)
    async_message = await agent.aget_system_message(session=session, run_context=run_context)

    for message in (sync_message, async_message):
        defs = _field_properties(message.content)["$defs"]
        assert defs["Priority"]["type"] == "integer"
        assert defs["Color"]["enum"] == ["red", "blue"]


@pytest.mark.asyncio
async def test_team_json_mode_system_message_describes_enums():
    member = Agent(name="Helper", model=OpenAIResponses(id="gpt-5.6-luna"))
    team = Team(members=[member], model=OpenAIResponses(id="gpt-5.6-luna"), output_schema=Ticket, use_json_mode=True)
    session = TeamSession(session_id="s1")
    run_context = RunContext(run_id="r1", session_id="s1", output_schema=Ticket)

    sync_message = team.get_system_message(session=session, run_context=run_context)
    async_message = await team.aget_system_message(session=session, run_context=run_context)

    for message in (sync_message, async_message):
        defs = _field_properties(message.content)["$defs"]
        assert defs["Priority"] == {"type": "integer", "enum": [1, 2], "description": ""}
        assert defs["Color"] == {"type": "string", "enum": ["red", "blue"], "description": ""}
        assert defs["Code"] == {"enum": ["text", 2], "description": ""}
