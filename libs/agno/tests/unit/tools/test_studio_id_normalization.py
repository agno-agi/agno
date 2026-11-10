"""Studio tools accept an id with stray whitespace and name the id when it does not resolve."""

import asyncio
import json

import pytest

from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.registry import Registry
from agno.tools.calculator import CalculatorTools
from agno.tools.studio import StudioTools, _clean_id


@pytest.fixture
def studio(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "studio.db"))
    registry = Registry(tools=[CalculatorTools()], models=[OpenAIResponses(id="gpt-5.5")], dbs=[db])
    tools = StudioTools(registry=registry, db=db, schedules=True)
    created = json.loads(tools.create_agent(name="Tone Checker", instructions="Judge the tone."))
    assert created["ok"] and created["data"]["id"] == "tone-checker", created
    return tools


def call(tools, tool, use_async, *args, **kwargs):
    if use_async:
        return json.loads(asyncio.run(getattr(tools, "a" + tool)(*args, **kwargs)))
    return json.loads(getattr(tools, tool)(*args, **kwargs))


@pytest.mark.parametrize(
    "sent", ["tone-checker ", "tone-checker  ", " tone-checker\n", "tone-checker ‬", "​tone-checker"]
)
def test_clean_id_strips_whitespace_and_invisible_marks(sent):
    assert _clean_id(sent) == "tone-checker"


def test_clean_id_keeps_everything_else():
    assert _clean_id("Tone Checker") == "Tone Checker"
    assert _clean_id("tone-checker”,") == "tone-checker”,"
    assert _clean_id(None) is None


@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize("sent", ["tone-checker ", "tone-checker  ", "tone-checker ‬"])
def test_read_resolves_an_id_with_stray_whitespace(studio, sent, use_async):
    read = call(studio, "get_component", use_async, sent)
    assert read["ok"] and read["data"]["id"] == "tone-checker", read


@pytest.mark.parametrize("use_async", [False, True])
def test_edit_and_publish_resolve_an_id_with_stray_whitespace(studio, use_async):
    edited = call(studio, "edit_agent", use_async, "tone-checker  ", instructions="Judge the tone. Suggest a rewrite.")
    assert edited["ok"] and edited["data"]["id"] == "tone-checker", edited
    published = call(studio, "publish_component", use_async, " tone-checker ")
    assert published["ok"], published
    read = call(studio, "get_component", use_async, "tone-checker")
    assert "Suggest a rewrite" in json.dumps(read["data"])


@pytest.mark.parametrize("use_async", [False, True])
def test_schedule_resolves_a_target_id_with_stray_whitespace(studio, use_async):
    assert call(studio, "publish_component", use_async, "tone-checker")["ok"]
    created = call(
        studio,
        "create_schedule",
        use_async,
        name="weekly",
        cron="0 9 * * 1",
        target_type="agent",
        target_id="tone-checker  ",
        message="go",
    )
    assert created["ok"], created
    assert "/agents/tone-checker/runs" in json.dumps(created["data"])


@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize("sent,stray", [("tone-checker”,", "”,"), ("tone-checkerانت", "انت"), ("tone-checker ئ", " ئ")])
def test_an_id_with_stray_characters_is_refused_and_named(studio, sent, stray, use_async):
    read = call(studio, "get_component", use_async, sent)
    assert not read["ok"] and read["error"]["code"] == "component_not_found", read
    message = read["error"]["message"]
    assert message.startswith("Component not found: " + sent)
    assert repr(stray) in message and "'tone-checker'" in message and "exactly as listed" in message


@pytest.mark.parametrize("use_async", [False, True])
def test_a_missing_plain_id_or_name_gets_the_plain_message(studio, use_async):
    for sent in ("payroll", "Payroll Agent"):
        read = call(studio, "get_component", use_async, sent)
        assert read["error"]["message"] == "Component not found: " + sent
