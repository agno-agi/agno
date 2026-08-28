"""Structured output for external framework adapters (BaseExternalAgent)."""

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest
from pydantic import BaseModel

from agno.agents.base import BaseExternalAgent
from agno.run.agent import RunContentEvent, RunEvent, RunOutput


class Review(BaseModel):
    verdict: str
    issues: List[str]


class Summary(BaseModel):
    headline: str


@dataclass
class FakeAgent(BaseExternalAgent):
    """Adapter that echoes a canned reply and records the input it was handed."""

    reply: str = ""
    framework: str = "fake"
    seen_inputs: List[Any] = field(default_factory=list)
    seen_schemas: List[Any] = field(default_factory=list)

    async def _arun_adapter(self, input: Any, *, history: Optional[List[Dict[str, Any]]] = None, **kwargs: Any) -> str:
        self.seen_inputs.append(input)
        self.seen_schemas.append(kwargs.get("output_schema"))
        return self.reply

    async def _arun_adapter_stream(
        self, input: Any, *, history: Optional[List[Dict[str, Any]]] = None, **kwargs: Any
    ) -> AsyncIterator[Any]:
        self.seen_inputs.append(input)
        self.seen_schemas.append(kwargs.get("output_schema"))
        # Split into chunks so the test exercises accumulation, not a single blob.
        mid = len(self.reply) // 2
        for chunk in (self.reply[:mid], self.reply[mid:]):
            yield RunContentEvent(
                run_id=kwargs.get("run_id", ""),
                agent_id=self.get_id(),
                agent_name=self.name or "",
                content=chunk,
            )


VALID_JSON = '{"verdict": "needs-changes", "issues": ["no tests"]}'


@pytest.mark.asyncio
async def test_arun_returns_validated_model():
    agent = FakeAgent(name="fake", reply=VALID_JSON)

    result = await agent.arun("Review this PR", output_schema=Review)

    assert isinstance(result, RunOutput)
    assert isinstance(result.content, Review)
    assert result.content.verdict == "needs-changes"
    assert result.content.issues == ["no tests"]
    assert result.content_type == "Review"


@pytest.mark.asyncio
async def test_agent_level_schema_applies_without_per_run_arg():
    agent = FakeAgent(name="fake", reply=VALID_JSON, output_schema=Review)

    result = await agent.arun("Review this PR")

    assert isinstance(result.content, Review)


@pytest.mark.asyncio
async def test_per_run_schema_overrides_agent_level():
    agent = FakeAgent(name="fake", reply='{"headline": "all good"}', output_schema=Review)

    result = await agent.arun("Summarize", output_schema=Summary)

    assert isinstance(result.content, Summary)
    assert result.content.headline == "all good"


@pytest.mark.asyncio
async def test_per_run_none_falls_through_to_agent_schema():
    """Mirrors native Agno: None at the call site does not clear the agent schema."""
    agent = FakeAgent(name="fake", reply=VALID_JSON, output_schema=Review)

    result = await agent.arun("Review this PR", output_schema=None)

    assert isinstance(result.content, Review)


@pytest.mark.asyncio
async def test_schema_instructions_appended_to_input():
    agent = FakeAgent(name="fake", reply=VALID_JSON)

    await agent.arun("Review this PR", output_schema=Review)

    sent = agent.seen_inputs[0]
    assert sent.startswith("Review this PR")
    assert "verdict" in sent and "issues" in sent
    assert agent.seen_schemas[0] is Review


@pytest.mark.asyncio
async def test_no_schema_leaves_input_and_content_untouched():
    agent = FakeAgent(name="fake", reply="just prose")

    result = await agent.arun("Say hi")

    assert agent.seen_inputs[0] == "Say hi"
    assert result.content == "just prose"
    assert result.content_type == "str"


@pytest.mark.asyncio
async def test_invalid_output_degrades_to_string_without_raising():
    """Matches native Agno: warn and hand back raw content rather than raising."""
    agent = FakeAgent(name="fake", reply="I could not do that")

    result = await agent.arun("Review this PR", output_schema=Review)

    assert result.content == "I could not do that"
    assert result.content_type == "str"


@pytest.mark.asyncio
async def test_json_wrapped_in_markdown_fence_is_parsed():
    agent = FakeAgent(name="fake", reply=f"Here you go:\n```json\n{VALID_JSON}\n```")

    result = await agent.arun("Review this PR", output_schema=Review)

    assert isinstance(result.content, Review)
    assert result.content.verdict == "needs-changes"


@pytest.mark.asyncio
async def test_stream_parses_accumulated_content_at_end():
    agent = FakeAgent(name="fake", reply=VALID_JSON)

    events = [e async for e in agent.arun("Review this PR", stream=True, output_schema=Review)]

    completed = [e for e in events if e.event == RunEvent.run_completed.value]
    assert len(completed) == 1
    assert isinstance(completed[0].content, Review)
    assert completed[0].content.verdict == "needs-changes"


@pytest.mark.asyncio
async def test_stream_content_events_stay_raw_text():
    """Only the terminal event carries the object; deltas remain text."""
    agent = FakeAgent(name="fake", reply=VALID_JSON)

    events = [e async for e in agent.arun("Review this PR", stream=True, output_schema=Review)]

    content_events = [e for e in events if e.event == RunEvent.run_content.value]
    assert len(content_events) > 1
    assert all(isinstance(e.content, str) for e in content_events)
    assert "".join(e.content for e in content_events) == VALID_JSON


@pytest.mark.asyncio
async def test_stream_invalid_output_degrades_to_string():
    agent = FakeAgent(name="fake", reply="not json at all")

    events = [e async for e in agent.arun("Review this PR", stream=True, output_schema=Review)]

    completed = [e for e in events if e.event == RunEvent.run_completed.value]
    assert completed[0].content == "not json at all"


def test_sync_run_returns_validated_model():
    agent = FakeAgent(name="fake", reply=VALID_JSON)

    result = agent.run("Review this PR", output_schema=Review)

    assert isinstance(result.content, Review)
    assert result.content.verdict == "needs-changes"


def test_sync_stream_returns_validated_model():
    agent = FakeAgent(name="fake", reply=VALID_JSON)

    events = list(agent.run("Review this PR", stream=True, output_schema=Review))

    completed = [e for e in events if e.event == RunEvent.run_completed.value]
    assert isinstance(completed[0].content, Review)
