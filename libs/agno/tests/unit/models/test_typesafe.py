import json
from dataclasses import dataclass, field
from typing import Annotated, Literal, Optional

import pytest
from pydantic import BaseModel

pytest.importorskip("typesafe_sdk")
from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, Score, SystemOneResponse, TypeSafeClient, TypeSafeError

from agno.agent import Agent
from agno.exceptions import InputCheckError, ModelProviderError, OutputCheckError
from agno.guardrails.typesafe import JevGuardrail
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.models.typesafe import Jev, JevAbstentionError, JevField
from agno.models.typesafe._schemas import compile_decisions
from agno.models.utils import get_model, get_model_from_dict
from agno.run.agent import RunInput, RunOutput
from agno.run.base import RunStatus
from agno.team import Team
from agno.tools.function import Function
from agno.tools.models.typesafe import JevTools


class Decision(BaseModel):
    risk: Annotated[float, JevField(Noul(instructions="Is state.input risky?"))]
    category: Annotated[
        Literal["billing", "support"],
        JevField(
            Choice(
                instructions="Classify the request", criteria={"billing": "Payments", "support": "Technical support"}
            )
        ),
    ]
    severity: Annotated[float, JevField(Score(instructions="Rate severity", criteria=["Low", "Medium", "High"]))]
    blocked: Annotated[bool, JevField(Noul(instructions="Should this be blocked?"), threshold=0.7)]


class FakeSDK:
    def __init__(self, choices=None, probability=0.8, confidence=0.9, error=None):
        self.calls = []
        self.choices = choices or {}
        self.probability = probability
        self.confidence = confidence
        self.error = error

    def system_one(self, state, questions, **kwargs):
        self.calls.append((state, questions, kwargs))
        if self.error:
            raise self.error
        answers = {}
        for key, question in questions.items():
            if question.type == "noul":
                answers[key] = {"type": "noul", "noul": self.probability}
            elif question.type == "choice":
                selected = self.choices.get(key, next(iter(question.criteria)))
                answers[key] = {
                    "type": "choice",
                    "choice": selected,
                    "confidence": self.confidence,
                    "probabilities": {label: 1.0 if label == selected else 0.0 for label in question.criteria},
                }
            else:
                answers[key] = {
                    "type": "score",
                    "score": 1.25,
                    "confidence": 0.6,
                    "legend": dict(enumerate(question.criteria)),
                    "probabilities": {0: 0.0, 1: 0.75, 2: 0.25},
                }
        return SystemOneResponse(model="jev-test", usage={"input_tokens": 17, "output_tokens": 4}, answers=answers)


class AsyncSDK(FakeSDK):
    async def system_one(self, *args, **kwargs):
        return super().system_one(*args, **kwargs)


@dataclass
class Echo(Model):
    id: str = "echo"
    provider: str = "test"
    inputs: list = field(default_factory=list)

    def invoke(self, messages, **kwargs):
        self.inputs.append(messages[-1].content)
        return ModelResponse(role="assistant", content="member result")

    async def ainvoke(self, *args, **kwargs):
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args, **kwargs):
        yield await self.ainvoke(*args, **kwargs)

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


def test_schema_values_metadata_and_serialized_schema():
    schema = Decision.model_json_schema()
    assert schema["properties"]["risk"]["type"] == "number"
    sdk = FakeSDK()
    agent = Agent(model=Jev(client=sdk), output_schema=Decision, telemetry=False)
    result = agent.run("refund")
    assert result.status == RunStatus.completed
    assert result.content == Decision(risk=0.8, category="billing", severity=1.25, blocked=True)
    assert result.model_provider_data["typesafe"]["answers"]["q2"]["probabilities"]["2"] == 0.25
    assert result.metrics.input_tokens == 17
    restored = Agent(model=Jev(client=sdk), output_schema=schema, telemetry=False).run("refund")
    assert restored.content == result.content.model_dump()


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_async_and_streaming_decisions(stream):
    sdk = AsyncSDK()
    agent = Agent(model=Jev(async_client=sdk), output_schema=Decision, telemetry=False)
    if stream:
        chunks = [chunk async for chunk in agent.arun("refund", stream=True)]
        assert len(chunks) == 1
        assert chunks[0].content.category == "billing"
    else:
        result = await agent.arun("refund")
        assert result.content.category == "billing"
    assert len(sdk.calls) == 1


def test_nested_schema_and_alias():
    from pydantic import Field

    class Nested(BaseModel):
        decision: Decision
        other: Annotated[float, JevField(Noul(instructions="Other risk"))] = Field(alias="otherRisk")

    compiled = compile_decisions(output_schema=Nested)
    assert compiled.fields["q4"][0] == ("otherRisk",)
    response = Jev(client=FakeSDK()).response([Message(role="user", content="test")], response_format=Nested)
    assert isinstance(response.parsed.decision, Decision)


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "properties": {"text": {"type": "string"}}},
        {"type": "object", "additionalProperties": {"type": "string"}},
        {
            "type": "object",
            "properties": {
                "risk": {"type": "boolean", "x-jev": {"question": {"type": "noul", "instructions": "Risk?"}}}
            },
        },
        {
            "type": "object",
            "properties": {
                "risk": {"type": "integer", "x-jev": {"question": {"type": "noul", "instructions": "Risk?"}}}
            },
        },
    ],
)
def test_unsupported_schema_fails_before_sdk(schema):
    sdk = FakeSDK()
    with pytest.raises(ValueError):
        Jev(client=sdk).invoke([Message(role="user", content="x")], response_format=schema)
    assert sdk.calls == []


def test_free_text_conflicts_and_media_rejected():
    model = Jev(client=FakeSDK())
    with pytest.raises(ValueError, match="free text"):
        model.invoke([Message(role="user", content="x")])
    model.questions = {"risk": Noul(instructions="Risk?")}
    with pytest.raises(ValueError, match="not both"):
        model.invoke([], response_format=Decision)
    with pytest.raises(ValueError, match="text content blocks"):
        model.invoke([Message(role="user", content=[{"type": "image_url", "image_url": {"url": "x"}}])])


def test_instructions_are_per_question_and_history_is_data():
    sdk = FakeSDK()
    question = Noul(instructions="Risk?")
    model = Jev(questions={"risk": question}, client=sdk)
    model.invoke(
        [Message(role="system", content="Follow this policy"), Message(role="user", content='{"text":"hello"}')]
    )
    state, questions, _ = sdk.calls[0]
    assert state["input"] == {"text": "hello"}
    assert questions["risk"].instructions["instructions"] == ["Follow this policy"]
    assert question.instructions == "Risk?"


def test_cache_key_and_serialization():
    messages = [Message(role="user", content="same")]
    model = Jev(questions={"risk": Noul(instructions="Risk?")}, api_key="secret")
    before = model._get_model_cache_key(messages, False)
    model.questions = {"risk": Noul(instructions="Different policy?")}
    assert before != model._get_model_cache_key(messages, False)
    assert "secret" not in json.dumps(model.to_dict())
    assert get_model_from_dict(model.to_dict()).to_dict() == model.to_dict()
    assert isinstance(get_model("typesafe:jev-latest"), Jev)
    router = Jev(mode="route", min_confidence=0.75, fallback_member_id="support")
    assert get_model_from_dict(router.to_dict()).to_dict() == router.to_dict()


def test_typed_cache_roundtrip(tmp_path):
    sdk = FakeSDK()
    model = Jev(client=sdk, cache_response=True, cache_dir=str(tmp_path))
    for _ in range(2):
        result = model.response([Message(role="user", content="same")], response_format=Decision)
        assert isinstance(result.parsed, Decision)
    assert len(sdk.calls) == 1


def set_switch(color: Literal["red", "green"], enabled: bool, level: Optional[Literal[1, 2]] = None) -> str:
    return json.dumps({"color": color, "enabled": enabled, "level": level})


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("stream", [False, True])
async def test_one_tool_dispatch_and_original_flags(async_mode, stream):
    sdk = AsyncSDK() if async_mode else FakeSDK()
    fn = Function.from_callable(set_switch)
    model = Jev(mode="tools", client=sdk, async_client=sdk)
    args = dict(messages=[Message(role="user", content="red")], tools=[fn])
    if stream:
        chunks = (
            [x async for x in model.aresponse_stream(**args)] if async_mode else list(model.response_stream(**args))
        )
        content = "".join(x.content or "" for x in chunks if x.event == ModelResponseEvent.assistant_response.value)
    else:
        response = await model.aresponse(**args) if async_mode else model.response(**args)
        content = response.content
    assert json.loads(content) == {"color": "red", "enabled": False, "level": 1}
    assert len(sdk.calls) == 1
    assert fn.stop_after_tool_call is False
    assert fn.show_result is False


def test_tool_none_forced_optional_and_unbounded():
    sdk = FakeSDK(choices={"select": "none"})
    model = Jev(mode="tools", client=sdk)
    tool = Function.from_callable(set_switch)
    assert json.loads(model.response([], tools=[tool]).content) == {"tool": None}
    assert json.loads(model.response([], tools=[tool], tool_choice="none").content) == {"tool": None}
    assert len(sdk.calls) == 1
    sdk.choices = {"present0_2": "omit"}
    result = model.response([], tools=[tool], tool_choice={"type": "function", "function": {"name": "set_switch"}})
    assert json.loads(result.content)["level"] is None

    def unbounded(text: str = "default") -> str:
        return text

    with pytest.raises(ValueError, match="finite"):
        model.response([], tools=[Function.from_callable(unbounded)])


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("stream", [False, True])
async def test_team_routes_once_and_preserves_input(async_mode, stream):
    sdk = AsyncSDK(choices={"select": "support"}) if async_mode else FakeSDK(choices={"select": "support"})
    billing_model, support_model = Echo(), Echo()
    team = Team(
        model=Jev(mode="route", client=sdk, async_client=sdk),
        mode="route",
        determine_input_for_members=False,
        members=[
            Agent(id="billing", name="Billing", role="Payments", model=billing_model, telemetry=False),
            Agent(id="support", name="Support", role="Technical", model=support_model, telemetry=False),
        ],
        telemetry=False,
    )
    if stream:
        chunks = (
            [c async for c in team.arun("original request", stream=True)]
            if async_mode
            else list(team.run("original request", stream=True))
        )
        assert "member result" in "".join(getattr(c, "content", "") or "" for c in chunks)
    else:
        result = await team.arun("original request") if async_mode else team.run("original request")
        assert result.status == RunStatus.completed
        assert "member result" in result.content
    assert len(sdk.calls) == 1
    assert billing_model.inputs == []
    assert len(support_model.inputs) == 1
    assert "original request" in support_model.inputs[0]
    criteria = sdk.calls[0][1]["select"].criteria
    assert set(criteria) == {"billing", "support"}
    assert criteria["support"]["role"] == "Technical"


def route_tool():
    return {
        "type": "function",
        "function": {
            "name": "delegate_task_to_member",
            "parameters": {
                "x-agno-route": {
                    "passthrough": True,
                    "members": [{"id": "a", "description": "A"}, {"id": "b", "description": "B"}],
                }
            },
        },
    }


def test_routing_threshold_fallback_and_unknown_member():
    sdk = FakeSDK(confidence=0.4)
    model = Jev(mode="route", client=sdk, min_confidence=0.7)
    with pytest.raises(JevAbstentionError):
        model.invoke([], tools=[route_tool()])
    model.fallback_member_id = "b"
    result = model.invoke([], tools=[route_tool()])
    assert json.loads(result.tool_calls[0]["function"]["arguments"])["member_id"] == "b"
    model.fallback_member_id = "missing"
    with pytest.raises(ValueError, match="roster"):
        model.invoke([], tools=[route_tool()])
    assert len(sdk.calls) == 2


def test_team_configuration_rejected():
    with pytest.raises(ValueError, match="requires"):
        Team(model=Jev(mode="route"), members=[Agent(model=Echo())], telemetry=False).initialize_team()
    with pytest.raises(ValueError, match="explicit model"):
        Team(
            model=Jev(mode="route"), mode="route", determine_input_for_members=False, members=[Agent()], telemetry=False
        ).initialize_team()


@pytest.mark.asyncio
async def test_tools_fixed_dynamic_and_async():
    tools = JevTools(output_schema=Decision, client=FakeSDK(), async_client=AsyncSDK())
    assert set(tools.get_functions()) == {"evaluate"}
    assert set(tools.get_async_functions()) == {"evaluate"}
    assert json.loads(tools.evaluate("test"))["values"]["risk"] == 0.8
    assert json.loads(await tools.aevaluate("test"))["values"]["risk"] == 0.8
    with pytest.raises(ValueError, match="disabled"):
        tools.evaluate_questions("test", {"risk": {"type": "noul", "instructions": "Risk?"}})
    dynamic = JevTools(allow_dynamic_questions=True, client=FakeSDK(), async_client=AsyncSDK())
    assert set(dynamic.get_functions()) == {"evaluate_questions"}
    assert json.loads(await dynamic.aevaluate_questions("test", {"risk": {"type": "noul", "instructions": "Risk?"}}))[
        "values"
    ] == {"risk": 0.8}


@pytest.mark.asyncio
async def test_guardrail_input_output_presets_and_async():
    guardrail = JevGuardrail.pii(threshold=0.7, client=FakeSDK(), async_client=AsyncSDK())
    with pytest.raises(InputCheckError) as exc:
        guardrail.check(RunInput(input_content="secret"))
    assert exc.value.additional_data["typesafe"]["answers"]["risk"]["noul"] == 0.8
    with pytest.raises(OutputCheckError):
        await guardrail.async_check(run_output=RunOutput(content="secret"))
    with pytest.raises(ValueError, match="evidence"):
        JevGuardrail.grounding(threshold=0.7, state_builder=lambda: {"output": "unsupported"}, client=FakeSDK()).check(
            RunInput(input_content="x")
        )


@pytest.mark.parametrize("component", [Agent, Team])
@pytest.mark.parametrize("bound", [False, True])
def test_output_stream_preflight(component, bound):
    guardrail = JevGuardrail.pii(threshold=0.7, client=FakeSDK())
    model = Echo()
    owner = component(
        model=model,
        post_hooks=[guardrail.check if bound else guardrail],
        telemetry=False,
        **({"members": []} if component is Team else {}),
    )
    with pytest.raises(ValueError, match="stream=False"):
        list(owner.run("x", stream=True))
    assert model.inputs == []


@pytest.mark.parametrize("component", [Agent, Team])
def test_guardrail_service_failure_never_passes(component):
    guardrail = JevGuardrail.pii(threshold=0.7, client=FakeSDK(error=TypeSafeError("unavailable")))
    model = Echo()
    owner = component(
        model=model, pre_hooks=[guardrail], telemetry=False, **({"members": []} if component is Team else {})
    )
    result = owner.run("x")
    assert result.status == RunStatus.error
    assert model.inputs == []


@pytest.mark.asyncio
async def test_official_sdk_transport_sync_async_and_error_mapping():
    import httpx2

    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx2.Response(
            200,
            headers={"x-typesafe-request-id": "request-123"},
            json={"model": "jev-test", "usage": {}, "answers": {"risk": {"type": "noul", "noul": 0.2}}},
        )

    questions = {"risk": Noul(instructions="Risk?")}
    with TypeSafeClient(api_key="fake-key", transport=httpx2.MockTransport(handler)) as client:
        result = Jev(questions=questions, client=client).invoke([Message(role="user", content="test")])
        assert result.provider_data["typesafe"]["request_id"] == "request-123"
    async with AsyncTypeSafeClient(api_key="fake-key", transport=httpx2.MockTransport(handler)) as client:
        result = await Jev(questions=questions, async_client=client).ainvoke([Message(role="user", content="test")])
        assert json.loads(result.content) == {"risk": 0.2}
    assert len(seen) == 2
    assert seen[0]["questions"]["risk"]["type"] == "noul"
    with pytest.raises(ModelProviderError, match="unavailable"):
        Jev(questions=questions, client=FakeSDK(error=TypeSafeError("unavailable"))).invoke([])


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("external", [False, True])
async def test_pause_resume_is_one_dispatch(async_mode, external):
    calls = []

    def action(enabled: bool) -> str:
        calls.append(enabled)
        return "action completed"

    fn = Function.from_callable(action)
    fn.requires_confirmation = not external
    fn.external_execution = external
    sdk = AsyncSDK() if async_mode else FakeSDK()
    agent = Agent(model=Jev(mode="tools", client=sdk, async_client=sdk), tools=[fn], telemetry=False)
    paused = await agent.arun("disable") if async_mode else agent.run("disable")
    assert paused.status == RunStatus.paused
    assert calls == []
    requirement = paused.requirements[0]
    if external:
        requirement.set_external_execution_result("external result")
    else:
        requirement.confirm()
    result = await agent.acontinue_run(paused) if async_mode else agent.continue_run(paused)
    assert result.status == RunStatus.completed
    assert len(sdk.calls) == 1
    assert calls == ([] if external else [False])
    assert result.content == ("external result" if external else "action completed")


@pytest.mark.asyncio
@pytest.mark.parametrize("component", [Agent, Team])
@pytest.mark.parametrize("post", [False, True])
async def test_async_guardrail_service_failure_and_content_suppression(component, post):
    guardrail = JevGuardrail.pii(threshold=0.7, async_client=AsyncSDK(error=TypeSafeError("unavailable")))
    model = Echo()
    owner = component(
        model=model,
        telemetry=False,
        **({"post_hooks": [guardrail]} if post else {"pre_hooks": [guardrail]}),
        **({"members": []} if component is Team else {}),
    )
    result = await owner.arun("x")
    assert result.status == RunStatus.error
    assert result.content != "member result"
    assert len(model.inputs) == (1 if post else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("component", [Agent, Team])
async def test_async_output_stream_preflight_and_input_stream_allowed(component):
    guardrail = JevGuardrail.pii(threshold=0.9, async_client=AsyncSDK())
    model = Echo()
    owner = component(
        model=model, post_hooks=[guardrail], telemetry=False, **({"members": []} if component is Team else {})
    )
    with pytest.raises(ValueError, match="stream=False"):
        [x async for x in owner.arun("x", stream=True)]
    assert model.inputs == []
    owner.post_hooks = None
    owner.pre_hooks = [guardrail]
    owner._hooks_normalised = False
    chunks = [x async for x in owner.arun("x", stream=True)]
    assert "member result" in "".join(getattr(x, "content", "") or "" for x in chunks)


@pytest.mark.parametrize("component", [Agent, Team])
@pytest.mark.parametrize("background", [False, True])
@pytest.mark.parametrize("post", [False, True])
def test_guardrail_errors_propagate_through_all_sync_hook_paths(component, background, post):
    from fastapi import BackgroundTasks

    guardrail = JevGuardrail.pii(threshold=0.7, client=FakeSDK(error=TypeSafeError("unavailable")))
    owner = component(
        model=Echo(),
        telemetry=False,
        **({"post_hooks": [guardrail]} if post else {"pre_hooks": [guardrail]}),
        **({"members": []} if component is Team else {}),
    )
    owner._run_hooks_in_background = background
    result = owner.run("x", background_tasks=BackgroundTasks() if background else None)
    assert result.status == RunStatus.error
    assert result.content != "member result"


def test_workflow_decision_step():
    from agno.workflow import Step, Workflow

    sdk = FakeSDK()
    classifier = Agent(model=Jev(client=sdk), output_schema=Decision, telemetry=False)
    workflow = Workflow(steps=[Step(name="Classify", agent=classifier)], telemetry=False)
    result = workflow.run("refund")
    assert len(sdk.calls) == 1
    assert result.step_results[0].content.category == "billing"


def test_serialized_schema_constraints_are_validated():
    from jsonschema.exceptions import ValidationError

    schema = Decision.model_json_schema()
    schema["properties"]["risk"]["maximum"] = 0.5
    with pytest.raises(ValidationError, match="maximum"):
        Jev(client=FakeSDK()).invoke([], response_format=schema)


def test_guardrail_message_input_and_media_rejection():
    from agno.media import Image

    sdk = FakeSDK(probability=0.1)
    guardrail = JevGuardrail.pii(threshold=0.7, client=sdk)
    guardrail.check(RunInput(input_content=[Message(role="user", content="hello")]))
    assert sdk.calls[0][0]["input"] == [{"role": "user", "content": "hello"}]
    output = RunOutput(content="image", images=[Image(url="https://example.test/image.png")])
    with pytest.raises(ValueError, match="text/JSON"):
        guardrail.check(run_output=output)
    assert output.content is None
    assert len(sdk.calls) == 1


def test_dynamic_roster_is_resolved_per_run():
    from agno.run import RunContext

    first = Agent(id="first", model=Echo(), telemetry=False)
    second = Agent(id="second", model=Echo(), telemetry=False)

    def members(run_context: RunContext):
        return [first] if run_context.user_id == "one" else [second]

    sdk = FakeSDK()
    team = Team(
        model=Jev(mode="route", client=sdk),
        mode="route",
        determine_input_for_members=False,
        members=members,
        telemetry=False,
    )
    assert team.run("x", user_id="one").status == RunStatus.completed
    assert team.run("y", user_id="two").status == RunStatus.completed
    assert set(sdk.calls[0][1]["select"].criteria) == {"first"}
    assert set(sdk.calls[1][1]["select"].criteria) == {"second"}


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
async def test_generative_agent_calls_jev_tool(async_mode):
    class ToolCaller(Echo):
        def invoke(self, messages, **kwargs):
            if not any(message.role == "tool" for message in messages):
                return ModelResponse(
                    role="assistant",
                    tool_calls=[
                        {
                            "id": "consult-jev",
                            "type": "function",
                            "function": {"name": "evaluate", "arguments": json.dumps({"state": "ticket"})},
                        }
                    ],
                )
            return ModelResponse(role="assistant", content=messages[-1].content)

    sdk = AsyncSDK() if async_mode else FakeSDK()
    tools = JevTools(questions={"risk": Noul(instructions="Risk?")}, client=sdk, async_client=sdk)
    agent = Agent(model=ToolCaller(), tools=[tools], telemetry=False)
    result = await agent.arun("classify") if async_mode else agent.run("classify")
    assert result.status == RunStatus.completed
    assert json.loads(result.content)["values"] == {"risk": 0.8}
    assert len(sdk.calls) == 1


@pytest.mark.parametrize(
    "filename",
    [
        "90_models/typesafe/questions.py",
        "90_models/typesafe/basic.py",
        "90_models/typesafe/async_basic.py",
        "90_models/typesafe/raw_questions.py",
        "90_models/typesafe/structured_output.py",
        "90_models/typesafe/tool_use.py",
        "90_models/typesafe/tools_use_with_fallback.py",
        "90_models/typesafe/async_decisions.py",
        "90_models/typesafe/route_team.py",
        "90_models/typesafe/workflow.py",
        "02_agents/08_guardrails/jev_guardrail.py",
        "02_agents/08_guardrails/jev_grounding.py",
        "03_teams/18_guardrails/jev_guardrail.py",
        "03_teams/02_modes/route/04_jev_router.py",
        "04_workflows/05_conditional_branching/router_jev_classifier.py",
        "91_tools/jev_tools.py",
        "91_tools/jev_tools_fixed_schema.py",
    ],
)
def test_cookbook_smoke_with_mocked_providers(filename, monkeypatch):
    import runpy
    from pathlib import Path

    import agno.models.typesafe._client as sdk_module
    from agno.models.openai import OpenAIResponses

    monkeypatch.setenv("AGNO_TELEMETRY", "false")
    monkeypatch.setattr(sdk_module, "TypeSafeClient", lambda **kwargs: FakeSDK(probability=0.1))
    monkeypatch.setattr(sdk_module, "AsyncTypeSafeClient", lambda **kwargs: AsyncSDK(probability=0.1))
    monkeypatch.setattr(
        OpenAIResponses,
        "invoke",
        lambda *args, **kwargs: ModelResponse(role="assistant", content="The premium plan allows 20 seats."),
    )
    monkeypatch.setattr(
        OpenAIResponses,
        "invoke_stream",
        lambda *args, **kwargs: iter([ModelResponse(role="assistant", content="The premium plan allows 20 seats.")]),
    )

    async def ainvoke(*args, **kwargs):
        return ModelResponse(role="assistant", content="The premium plan allows 20 seats.")

    monkeypatch.setattr(OpenAIResponses, "ainvoke", ainvoke)
    path = Path(__file__).resolve().parents[5] / "cookbook" / filename
    runpy.run_path(str(path), run_name="__main__")


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("output", [False, True])
async def test_guardrail_named_checks_batch_and_per_question_threshold(async_mode, output):
    from agno.exceptions import CheckTrigger
    from agno.guardrails import JevGuardrail as PublicGuardrail

    sdk = AsyncSDK() if async_mode else FakeSDK()
    guardrail = PublicGuardrail(
        checks=["pii", "prompt_injection"],
        questions={
            "off_topic": {
                "instructions": "Is the content unrelated to travel?",
                "threshold": 0.8,
                "check_trigger": "off_topic",
            }
        },
        threshold=0.9,
        client=sdk,
        async_client=sdk,
    )
    run_output = RunOutput(content="content") if output else None
    args = {"run_output": run_output} if output else {"run_input": RunInput(input_content="content")}
    with pytest.raises(OutputCheckError if output else InputCheckError) as exc:
        if async_mode:
            await guardrail.async_check(**args)
        else:
            guardrail.check(**args)
    assert len(sdk.calls) == 1
    assert sdk.calls[0][0] == {"output" if output else "input": "content"}
    assert set(sdk.calls[0][1]) == {"pii", "prompt_injection", "off_topic"}
    assert exc.value.additional_data["failed"] == ["off_topic"]
    assert exc.value.additional_data["thresholds"] == {"pii": 0.9, "prompt_injection": 0.9, "off_topic": 0.8}
    assert exc.value.check_trigger == (CheckTrigger.OUTPUT_NOT_ALLOWED if output else CheckTrigger.OFF_TOPIC)
    assert "off_topic (0.80)" in str(exc.value)
    if output:
        assert run_output.content is None
        assert run_output.model_provider_data["typesafe_guardrails"][0]["answers"]["off_topic"]["noul"] == 0.8


def test_guardrail_defaults_shorthand_and_distinct_output_questions():
    defaults = JevGuardrail()
    assert set(defaults.schema.questions) == {"prompt_injection", "harmful_request"}
    for name in defaults.schema.questions:
        assert defaults.schema.questions[name].instructions != defaults.output_check_schema.questions[name].instructions
    sdk = FakeSDK(probability=0.2)
    custom = JevGuardrail(questions={"off_topic": "Is the content unrelated to travel?"}, client=sdk)
    custom.check(run_input=RunInput(input_content="Kyoto"))
    assert set(sdk.calls[0][1]) == {"off_topic"}
    with pytest.raises(TypeSafeError, match="unavailable"):
        JevGuardrail(checks=["pii"], client=FakeSDK(error=TypeSafeError("unavailable"))).check(
            run_input=RunInput(input_content="content")
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"checks": ["unknown"]},
        {"checks": ["pii", "pii"]},
        {"checks": ["pii"], "questions": {"pii": "Duplicate?"}},
        {"checks": []},
        {"threshold": float("nan")},
        {"threshold": True},
        {"threshold": 1.1},
        {"questions": {"risk": {"instructions": "Risk?", "threshold": -0.1}}},
        {"questions": {"risk": {"instructions": "Risk?", "check_trigger": "missing"}}},
        {"questions": {"risk": {"type": "choice", "instructions": "Risk?", "criteria": {"a": None}}}},
        {"questions": {"risk": {"instructions": "Risk?", "criteria": {"yes": "yes", "no": "no"}}}},
        {"questions": {"risk": ""}},
        {"output_schema": Decision},
        {"checks": ["pii"], "block_when": lambda values: False},
    ],
)
def test_guardrail_shorthand_invalid_configuration_fails_locally(kwargs):
    with pytest.raises(ValueError):
        JevGuardrail(**kwargs)


def ask_questions():
    return [
        {"id": "risk", "type": "noul", "instructions": "Is state.ticket risky?", "options": []},
        {
            "id": "queue",
            "type": "choice",
            "instructions": "Which queue fits state.ticket?",
            "options": ["billing", "tech"],
        },
        {
            "id": "impact",
            "type": "score",
            "instructions": "Rate the impact of state.ticket.",
            "options": ["low", "medium", "high"],
        },
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
async def test_ask_jev_typed_questions_and_json_state(async_mode):
    from jsonschema import Draft202012Validator
    from agno.tools.typesafe import JevTools as PublicTools

    sdk = AsyncSDK() if async_mode else FakeSDK()
    toolkit = PublicTools(client=sdk, async_client=sdk)
    assert set(toolkit.get_functions()) == set(toolkit.get_async_functions()) == {"ask_jev"}
    args = {"state": '{"ticket": "refund"}', "questions": ask_questions()}
    parameters = toolkit.get_functions()["ask_jev"].parameters
    Draft202012Validator.check_schema(parameters)
    Draft202012Validator(parameters).validate(args)
    result = await toolkit.aask_jev(**args) if async_mode else toolkit.ask_jev(**args)
    assert json.loads(result)["values"] == {"risk": 0.8, "queue": "billing", "impact": 1.25}
    assert json.loads(result)["typesafe"]["answers"]["risk"]["noul"] == 0.8
    assert len(sdk.calls) == 1
    assert sdk.calls[0][0] == {"ticket": "refund"}
    assert sdk.calls[0][1]["risk"].type == "noul"
    assert set(sdk.calls[0][1]["queue"].criteria) == {"billing", "tech"}
    assert toolkit.add_instructions and "options=[]" in toolkit.instructions


@pytest.mark.parametrize(
    "questions",
    [
        [],
        [ask_questions()[0], ask_questions()[0]],
        [{**ask_questions()[0], "id": "  "}],
        [{**ask_questions()[0], "instructions": ""}],
        [{**ask_questions()[0], "options": ["yes", "no"]}],
        [{**ask_questions()[0], "criteria": {"yes": "yes", "no": "no"}}],
        [{**ask_questions()[1], "options": []}],
        [{**ask_questions()[1], "options": ["a", "a"]}],
        [{**ask_questions()[1], "options": ["  "]}],
        [{**ask_questions()[1], "options": [str(i) for i in range(256)]}],
        [{**ask_questions()[2], "options": ["only one"]}],
        [{**ask_questions()[2], "options": [str(i) for i in range(11)]}],
    ],
)
def test_ask_jev_rejects_invalid_questions_before_request(questions):
    sdk = FakeSDK()
    with pytest.raises(ValueError):
        JevTools(client=sdk).ask_jev("content", questions)
    assert sdk.calls == []


def test_ask_jev_registration_and_disable_controls():
    fixed = JevTools(output_schema=Decision)
    assert set(fixed.get_functions()) == {"evaluate"}
    with pytest.raises(ValueError, match="disabled"):
        fixed.ask_jev("content", ask_questions())
    both = JevTools(output_schema=Decision, enable_ask_jev=True)
    assert set(both.get_functions()) == {"evaluate", "ask_jev"}
    dynamic = JevTools(
        output_schema=Decision,
        enable_evaluate=False,
        enable_ask_jev=True,
        instructions="Custom guidance",
        add_instructions=False,
    )
    assert set(dynamic.get_functions()) == {"ask_jev"}
    assert dynamic.instructions == "Custom guidance" and not dynamic.add_instructions
    with pytest.raises(ValueError):
        dynamic.evaluate("content")
    with pytest.raises(ValueError):
        JevTools(enable_ask_jev=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
async def test_generative_agent_calls_ask_jev_with_json_arguments(async_mode):
    class QuestionAuthor(Echo):
        def invoke(self, messages, **kwargs):
            assert any("options=[]" in (m.content or "") for m in messages if m.role == "system")
            if not any(message.role == "tool" for message in messages):
                return ModelResponse(
                    role="assistant",
                    tool_calls=[
                        {
                            "id": "ask",
                            "type": "function",
                            "function": {
                                "name": "ask_jev",
                                "arguments": json.dumps(
                                    {"state": '{"ticket": "refund"}', "questions": ask_questions()}
                                ),
                            },
                        }
                    ],
                )
            return ModelResponse(role="assistant", content=messages[-1].content)

    sdk = AsyncSDK() if async_mode else FakeSDK()
    agent = Agent(model=QuestionAuthor(), tools=[JevTools(client=sdk, async_client=sdk)], telemetry=False)
    result = await agent.arun("classify") if async_mode else agent.run("classify")
    assert result.status == RunStatus.completed
    assert json.loads(result.content)["values"]["impact"] == 1.25
    assert len(sdk.calls) == 1


@pytest.mark.parametrize("mode", ["questions", "route", "tools"])
def test_jev_rejects_broadcast_leader_before_execution(mode):
    sdk = FakeSDK()
    member_model = Echo()
    team = Team(
        model=Jev(mode=mode, client=sdk),
        mode="broadcast",
        determine_input_for_members=False,
        output_schema=Decision,
        members=[Agent(model=member_model, telemetry=False)],
        telemetry=False,
    )
    with pytest.raises(ValueError, match="Team\\(mode='route'\\)"):
        team.initialize_team()
    assert sdk.calls == []
    assert member_model.inputs == []


def test_removed_judge_mode_is_rejected():
    sdk = FakeSDK()
    with pytest.raises(ValueError, match="Unknown Jev mode: judge"):
        Jev(mode="judge", client=sdk).invoke([Message(role="user", content="proposal")], response_format=Decision)
    assert sdk.calls == []


@pytest.mark.asyncio
async def test_review_cookbook_concurrent_requests_share_async_client(monkeypatch):
    import asyncio
    import runpy
    from pathlib import Path

    class ConcurrentSDK(FakeSDK):
        active = 0
        peak = 0

        async def system_one(self, *args, **kwargs):
            self.active += 1
            self.peak = max(self.peak, self.active)
            await asyncio.sleep(0)
            self.active -= 1
            return super().system_one(*args, **kwargs)

    monkeypatch.setenv("AGNO_TELEMETRY", "false")
    monkeypatch.setattr("rich.pretty.pprint", lambda *args, **kwargs: None)
    path = Path(__file__).resolve().parents[5] / "cookbook/90_models/typesafe/async_basic.py"
    example = runpy.run_path(str(path))
    sdk = ConcurrentSDK()
    example["agent"].model.async_client = sdk
    await example["main"]()
    runs = [await example["agent"].aget_last_run_output(session_id=f"review-{index}") for index in range(3)]
    assert sdk.peak == 3
    assert len(sdk.calls) == len(runs) == 3
    assert {run.session_id for run in runs} == {"review-0", "review-1", "review-2"}
    assert {call[0]["input"] for call in sdk.calls} == set(example["REVIEWS"])
    for run in runs:
        assert run.status == RunStatus.completed
        review = example["Review"].model_validate(run.content)
        assert review.topics.model_dump() == dict.fromkeys(("price", "quality", "shipping", "support"), True)
        assert review.would_recommend is True


@pytest.mark.parametrize(
    "choices, expected, fallback",
    [
        # Agno orders function names as lock_doors, set_lights, set_thermostat.
        ({"select": "t1", "arg1_0": "v1", "arg1_1": "v0", "present1_2": "omit"}, "bedroom lights off (warm)", False),
        ({"select": "t2", "arg2_0": "v0"}, "thermostat set to heat", False),
        ({"select": "t0", "arg0_0": "v1", "arg0_2": "v1"}, "locked: front, garage", False),
        ({"select": "none"}, "member result", True),
    ],
)
def test_smart_home_cookbook_tool_selection_and_explicit_fallback(monkeypatch, choices, expected, fallback):
    import runpy
    from pathlib import Path

    monkeypatch.setenv("AGNO_TELEMETRY", "false")
    path = Path(__file__).resolve().parents[5] / "cookbook/90_models/typesafe/tools_use_with_fallback.py"
    example = runpy.run_path(str(path))
    sdk = FakeSDK(choices=choices)
    example["agent"].model.client = sdk
    fallback_model = Echo()
    example["fallback_agent"].model = fallback_model
    result = example["respond_to_command"]("original command")
    assert result.status == RunStatus.completed
    assert result.content == expected
    assert len(sdk.calls) == 1
    assert len(fallback_model.inputs) == int(fallback)
    if fallback:
        assert "original command" in fallback_model.inputs[0]
    else:
        assert len(result.tools) == 1


def test_smart_home_cookbook_does_not_fallback_on_sdk_failure(monkeypatch):
    import runpy
    from pathlib import Path

    monkeypatch.setenv("AGNO_TELEMETRY", "false")
    path = Path(__file__).resolve().parents[5] / "cookbook/90_models/typesafe/tools_use_with_fallback.py"
    example = runpy.run_path(str(path))
    example["agent"].model.client = FakeSDK(error=TypeSafeError("unavailable"))
    fallback_model = Echo()
    example["fallback_agent"].model = fallback_model
    result = example["respond_to_command"]("original command")
    assert result.status == RunStatus.error
    assert fallback_model.inputs == []


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("department", ["billing", "technical"])
def test_agent_os_cookbook_classifies_and_routes_via_api(monkeypatch, stream, department):
    import runpy
    from pathlib import Path

    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from agno.db.in_memory import InMemoryDb

    monkeypatch.setenv("AGNO_TELEMETRY", "false")
    monkeypatch.delenv("OS_SECURITY_KEY", raising=False)
    monkeypatch.setattr("agno.db.sqlite.SqliteDb", lambda **kwargs: InMemoryDb())
    path = Path(__file__).resolve().parents[5] / "cookbook/90_models/typesafe/agent_os.py"
    example = runpy.run_path(str(path))
    classifier_sdk = AsyncSDK(choices={"q0": department})
    router_sdk = AsyncSDK(choices={"select": department})
    example["classifier"].model.async_client = classifier_sdk
    example["support_team"].model.async_client = router_sdk
    billing_model, technical_model = Echo(), Echo()
    example["billing"].model = billing_model
    example["technical"].model = technical_model
    message = "Please refund a duplicate charge" if department == "billing" else "Our workspace is down"
    data = {"message": message, "stream": str(stream).lower()}

    with TestClient(example["app"]) as client:
        assert client.get("/config").status_code == 200
        assert client.get("/openapi.json").status_code == 200
        classification = client.post("/agents/ticket-classifier/runs", data=data)
        routed = client.post("/teams/support-router/runs", data=data)

    assert classification.status_code == routed.status_code == 200
    if stream:
        assert classification.headers["content-type"].startswith("text/event-stream")
        assert department in classification.text
        assert "member result" in routed.text
        assert "RunError" not in classification.text + routed.text
    else:
        assert classification.json()["content"] == {"department": department, "urgent": True}
        assert routed.json()["content"] == "member result"
    assert len(classifier_sdk.calls) == len(router_sdk.calls) == 1
    selected = billing_model if department == "billing" else technical_model
    unselected = technical_model if department == "billing" else billing_model
    assert len(selected.inputs) == 1
    assert message in selected.inputs[0]
    assert unselected.inputs == []
