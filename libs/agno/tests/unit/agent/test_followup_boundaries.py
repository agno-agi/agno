import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.agent import Agent, FollowupConfig
from agno.agent import _response as agent_response
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run.agent import Followups, RunInput, RunOutput
from agno.run.team import TeamRunInput, TeamRunOutput
from agno.team import Team
from agno.team import _response as team_response


@pytest.mark.parametrize("kind", ["agent", "team"])
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("source", ["config", "legacy", "component"])
@pytest.mark.parametrize("suggestions", [[], ["Explain the documented workflow steps"], ["One", "Two", "Three"]])
async def test_generation_paths(kind, asynchronous, stream, source, suggestions):
    model = MagicMock(spec=Model)
    model.id, model.provider = "followup-test", "test"
    model.supports_native_structured_outputs = False
    model.supports_json_schema_outputs = False
    result = ModelResponse(content=json.dumps({"suggestions": suggestions}))
    model.response.return_value = result
    model.aresponse = AsyncMock(return_value=result)
    unused = MagicMock(spec=Model)
    config = FollowupConfig(instructions="Suggest only documentation questions.")
    if source == "config":
        config.model = model
    options = dict(
        followups=True,
        num_followups=2,
        followup_config=config,
        followup_model=model if source == "legacy" else unused if source == "config" else None,
        model=model if source == "component" else unused,
        telemetry=False,
    )
    if kind == "agent":
        component = Agent(**options)
        output = RunOutput(run_id="run", content="I can help with documentation.", input=RunInput(input_content="Hi"))
        module, name = agent_response, "generate_followups"
    else:
        component = Team(members=[], **options)
        output = TeamRunOutput(
            run_id="run", content="I can help with documentation.", input=TeamRunInput(input_content="Hi")
        )
        module, name = team_response, "generate_team_followups"
    function = getattr(module, ("a" if asynchronous else "") + name + ("_stream" if stream else ""))
    events = []
    if stream:
        if asynchronous:
            events = [event async for event in function(component, output)]
        else:
            events = list(function(component, output))
    elif asynchronous:
        await function(component, output)
    else:
        function(component, output)
    assert output.followups == suggestions[:2]
    if stream:
        assert events[-1].followups == suggestions[:2]
    assert type(output).from_dict(output.to_dict()).followups == suggestions[:2]
    call = model.aresponse.call_args if asynchronous else model.response.call_args
    assert call.kwargs["response_format"] == {"type": "json_object"}
    messages = call.kwargs["messages"]
    assert "Suggest only documentation questions." in messages[0].content
    assert "json" in messages[0].content.lower()
    assert "Never suggest repeating or fulfilling a request the assistant declined" in messages[0].content
    assert "Generate at most 2" in messages[1].content
    unused.response.assert_not_called()


@pytest.mark.parametrize("parsed", [Followups(suggestions=[]), {"suggestions": []}])
def test_empty_structured_followups_are_successful(parsed):
    assert agent_response._parse_followups_response(ModelResponse(parsed=parsed), 3) == []
