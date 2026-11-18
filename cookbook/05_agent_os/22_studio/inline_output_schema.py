"""
Give a Studio-built Agent an inline output schema
=================================================

StudioTools can attach a structured output schema without registering a Pydantic
class: create_agent takes a plain JSON Schema. The schema is stored with the
component and loads back as a Pydantic model, so a run returns a typed instance.
A schema that cannot be represented faithfully is refused, and nothing is stored.

Prerequisites: OPENAI_API_KEY
Run: python cookbook/05_agent_os/22_studio/inline_output_schema.py
Try: add "uniqueItems": true to a property and read the refusal
"""

import json
from pathlib import Path
from uuid import uuid4

from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.utils import get_agent_by_id
from agno.registry import Registry
from agno.tools.studio import StudioTools
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Create Studio Tools
# ---------------------------------------------------------------------------

DB_DIR = Path(__file__).parent / "tmp"
DB_DIR.mkdir(exist_ok=True)

db = SqliteDb(
    id="inline-output-schema-db",
    db_file=str(DB_DIR / "inline_output_schema.db"),
)

registry = Registry(
    name="Inline Output Schema Registry",
    models=[OpenAIResponses(id="gpt-5.6-luna")],
    dbs=[db],
)

studio_tools = StudioTools(
    registry=registry,
    db=db,
    default_model_id="gpt-5.6-luna",
)

# "nickname" is not required: a run returns None when the text does not state it.
PERSON_SCHEMA = {
    "type": "object",
    "title": "Person",
    "properties": {
        "name": {"type": "string", "description": "The person's name"},
        "role": {"enum": ["engineer", "designer", "manager"]},
        "nickname": {"type": "string", "description": "Only if the text states one"},
    },
    "required": ["name", "role"],
}


# ---------------------------------------------------------------------------
# Create, load, and run an Agent with an inline schema
# ---------------------------------------------------------------------------


def run_inline_schema() -> None:
    """Store a plain JSON Schema, load the Agent back, and read a typed result."""
    created = json.loads(
        studio_tools.create_agent(
            name=f"Person Extractor {uuid4().hex[:8]}",
            instructions="Extract the person from the text. Never guess a value.",
            output_schema=PERSON_SCHEMA,
            publish=True,
        )
    )
    if not created["ok"]:
        raise RuntimeError(f"create_agent failed: {created['error']}")
    component_id = created["data"]["id"]
    print(f"Created agent: {component_id}")

    # get_component shows the plain schema, so a read then edit changes nothing.
    view = json.loads(studio_tools.get_component(component_id))
    print(f"Stored schema title: {view['data']['output_schema']['title']}")

    agent = get_agent_by_id(component_id, agents=None, db=db, registry=registry)
    if agent is None:
        raise RuntimeError("The stored Agent did not load")
    print(f"Loaded output_schema: {agent.output_schema.__name__}")

    response = agent.run("Dana joined the team as a designer.")
    if not isinstance(response.content, BaseModel):
        raise RuntimeError(f"Expected a typed result, got {response.content!r}")
    print(f"Run content type: {type(response.content).__name__}")
    print(f"Run content: {response.content.model_dump()}")


# ---------------------------------------------------------------------------
# Read a refusal
# ---------------------------------------------------------------------------


def show_refusal() -> None:
    """A schema the converter cannot represent is refused with the reason."""
    refused = json.loads(
        studio_tools.create_agent(
            name=f"Tag Extractor {uuid4().hex[:8]}",
            instructions="Extract the tags.",
            output_schema={
                "type": "object",
                "properties": {
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "uniqueItems": True,
                    }
                },
            },
        )
    )
    if refused["ok"] or refused["error"]["code"] != "invalid_request":
        raise RuntimeError(f"Expected invalid_request, got {refused}")
    print(f"Refused: {refused['error']['code']}")
    print(f"Reason: {refused['error']['message']}")


if __name__ == "__main__":
    run_inline_schema()
    show_refusal()
