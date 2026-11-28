"""Unit tests for GoogleADKAgent.

These drive a real ADK Runner with a scripted ADK agent (a BaseAgent subclass that yields
events). No model is called.
"""

import asyncio
from typing import Any, AsyncGenerator, List

import pytest

pytest.importorskip("google.adk")

from google.adk.agents import BaseAgent  # noqa: E402
from google.adk.agents.invocation_context import InvocationContext  # noqa: E402
from google.adk.agents.run_config import RunConfig, StreamingMode  # noqa: E402
from google.adk.events import Event  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

from agno.agents.google_adk import GoogleADKAgent  # noqa: E402
from agno.db.sqlite import SqliteDb  # noqa: E402
from agno.media import Audio, File, Image, Video  # noqa: E402
from agno.run.agent import (  # noqa: E402
    RunCompletedEvent,
    RunContentEvent,
    RunErrorEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agno.run.base import RunStatus  # noqa: E402

USAGE = types.GenerateContentResponseUsageMetadata(
    prompt_token_count=10, candidates_token_count=4, total_token_count=14, thoughts_token_count=2
)


def _text(text: str) -> types.Content:
    return types.Content(role="model", parts=[types.Part.from_text(text=text)])


class ScriptedAgent(BaseAgent):
    """Replays a scripted event list; records every invocation it receives."""

    script: List[Any] = []
    invocations: List[InvocationContext] = []
    hang: bool = False

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        self.invocations.append(ctx)
        if self.hang:
            # Keep producing until the runner stops consuming, as a long model turn would.
            for _ in range(600):
                yield Event(author=self.name, invocation_id=ctx.invocation_id, partial=True, content=_text("."))
                await asyncio.sleep(0.05)
        for item in self.script:
            if isinstance(item, Event):
                yield item.model_copy(update={"author": self.name, "invocation_id": ctx.invocation_id})
            else:
                kwargs = dict(item)
                if "text" in kwargs:
                    kwargs["content"] = _text(kwargs.pop("text"))
                kwargs.setdefault("author", self.name)
                yield Event(invocation_id=ctx.invocation_id, **kwargs)


TOOL_SCRIPT = [
    {
        "content": types.Content(
            role="model",
            parts=[
                types.Part(function_call=types.FunctionCall(id="call-1", name="get_weather", args={"city": "Paris"}))
            ],
        ),
        "usage_metadata": USAGE,
    },
    {
        "content": types.Content(
            role="model",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        id="call-1", name="get_weather", response={"result": "sunny"}
                    )
                )
            ],
        ),
    },
    {"text": "It is ", "partial": True},
    {"text": "sunny", "partial": True},
    {"text": "It is sunny", "usage_metadata": USAGE, "model_version": "gemini-test"},
]


def _agent(script, db=None, name="Scripted", **kwargs):
    adk_agent = ScriptedAgent(name="scripted", script=script, invocations=[])
    return GoogleADKAgent(name=name, agent=adk_agent, db=db, **kwargs), adk_agent


def test_non_stream_collects_answer_tools_and_usage():
    agent, adk_agent = _agent(TOOL_SCRIPT)
    result = agent.run("weather?")
    assert result.status == RunStatus.completed
    assert result.content == "It is sunny"
    assert [(tool.tool_name, tool.tool_args, tool.result) for tool in result.tools] == [
        ("get_weather", {"city": "Paris"}, "sunny")
    ]
    assert result.metrics.input_tokens == 20
    assert result.metrics.output_tokens == 8
    assert result.metrics.reasoning_tokens == 4
    assert [(m.id, m.provider) for m in result.metrics.details["model"]] == [("", "Google"), ("gemini-test", "Google")]
    assert result.model is None and result.model_provider is None
    assert adk_agent.invocations[0].user_content.parts[0].text == "weather?"


def test_stream_emits_partials_once_and_tool_events():
    agent, _ = _agent(TOOL_SCRIPT)
    events = list(agent.run("weather?", stream=True))
    content = [event.content for event in events if isinstance(event, RunContentEvent)]
    assert content == ["It is ", "sunny"]
    started = [event for event in events if isinstance(event, ToolCallStartedEvent)]
    completed = [event for event in events if isinstance(event, ToolCallCompletedEvent)]
    assert started[0].tool.tool_call_id == completed[0].tool.tool_call_id == "call-1"
    assert completed[0].tool.result == "sunny"
    done = events[-1]
    assert isinstance(done, RunCompletedEvent) and done.content == "It is sunny"
    assert done.metrics.total_tokens == 28


def test_stream_run_config_switches_to_sse_without_touching_the_configured_one():
    agent, adk_agent = _agent(TOOL_SCRIPT, run_config=RunConfig(max_llm_calls=3))
    list(agent.run("weather?", stream=True))
    streamed = adk_agent.invocations[0].run_config
    assert streamed.streaming_mode == StreamingMode.SSE and streamed.max_llm_calls == 3
    assert agent.run_config.streaming_mode in (None, StreamingMode.NONE)
    agent.run("weather?")
    assert adk_agent.invocations[1].run_config.streaming_mode in (None, StreamingMode.NONE)


def test_successive_model_turns_are_separated_the_same_way_in_both_paths():
    script = [
        {"text": "Step one"},
        {"text": "Step ", "partial": True},
        {"text": "two", "partial": True},
        {"text": "Step two"},
    ]
    agent, _ = _agent(script)
    assert agent.run("go").content == "Step one\n\nStep two"
    events = list(agent.run("go", stream=True))
    assert "".join(event.content for event in events if isinstance(event, RunContentEvent)) == "Step one\n\nStep two"


def test_thoughts_are_not_content():
    content = types.Content(
        role="model", parts=[types.Part(text="thinking...", thought=True), types.Part.from_text(text="answer")]
    )
    agent, _ = _agent([{"content": content}])
    assert agent.run("q").content == "answer"


def test_tool_response_without_id_is_matched_by_name_and_errors_are_flagged():
    script = [
        {
            "content": types.Content(
                role="model", parts=[types.Part(function_call=types.FunctionCall(name="lookup", args={"q": 1}))]
            )
        },
        {
            "content": types.Content(
                role="model",
                parts=[types.Part(function_response=types.FunctionResponse(name="lookup", response={"error": "boom"}))],
            )
        },
        {"text": "failed"},
    ]
    agent, _ = _agent(script)
    result = agent.run("q")
    assert len(result.tools) == 1
    tool = result.tools[0]
    assert tool.tool_name == "lookup" and tool.tool_call_error is True and "boom" in tool.result


def test_model_error_event_fails_the_run():
    agent, _ = _agent([{"error_code": "MALFORMED_FUNCTION_CALL", "error_message": "bad call"}])
    result = agent.run("q")
    assert result.status == RunStatus.error and "MALFORMED_FUNCTION_CALL" in result.content
    events = list(agent.run("q", stream=True))
    assert isinstance(events[-1], RunErrorEvent)


def test_sessions_resume_natively_and_replay_history_when_the_native_session_is_gone(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "runs.db"))
    service = InMemorySessionService()
    agent, adk_agent = _agent([{"text": "hi"}], db=db, session_service=service)
    agent.run("first", session_id="s1", user_id="u1")
    agent.run("second", session_id="s1", user_id="u1")
    first, second = adk_agent.invocations
    assert first.user_content.parts[0].text == "first"
    # The ADK session carries the first turn, so the second prompt is sent as is.
    assert second.user_content.parts[0].text == "second"
    assert len(second.session.events) >= 2
    native = asyncio.run(service.get_session(app_name="agno", user_id="u1", session_id="s1"))
    assert native is not None and native.id == "s1"

    # A new process: fresh session service, same Agno database. The stored turns are replayed.
    fresh, fresh_adk = _agent([{"text": "hi"}], db=db)
    fresh.run("third", session_id="s1", user_id="u1")
    prompt = fresh_adk.invocations[0].user_content.parts[0].text
    assert prompt.startswith("Previous conversation")
    assert "user: first" in prompt and "assistant: hi" in prompt and prompt.endswith("Current message:\nthird")
    assert len(db.get_runs(session_id="s1")) == 3


def test_media_is_sent_as_native_parts(tmp_path):
    agent, adk_agent = _agent([{"text": "seen"}])
    path = tmp_path / "doc.txt"
    path.write_text("hello")
    result = agent.run(
        "look",
        images=[Image(content=b"png-bytes", format="png")],
        audio=[Audio(content=b"wav", mime_type="audio/wav")],
        videos=[Video(url="gs://bucket/clip.mp4")],
        files=[File(filepath=str(path))],
    )
    assert result.status == RunStatus.completed
    parts = adk_agent.invocations[0].user_content.parts
    assert parts[0].text == "look"
    assert (parts[1].inline_data.data, parts[1].inline_data.mime_type) == (b"png-bytes", "image/png")
    assert parts[2].inline_data.mime_type == "audio/wav"
    assert (parts[3].file_data.file_uri, parts[3].file_data.mime_type) == ("gs://bucket/clip.mp4", "video/mp4")
    assert (parts[4].inline_data.data, parts[4].inline_data.mime_type) == (b"hello", "text/plain")
    assert result.input.images[0].format == "png"


def test_cancel_stops_the_native_run():
    agent, _ = _agent([{"text": "late"}], db=None)
    agent.agent.hang = True

    async def scenario():
        task = asyncio.ensure_future(agent.arun("q", run_id="run-1"))
        await asyncio.sleep(0.2)
        assert await agent.acancel_run("run-1")
        return await asyncio.wait_for(task, timeout=5)

    result = asyncio.run(scenario())
    assert result.status == RunStatus.cancelled
    assert len(result.content or "") < 100


def test_prebuilt_runner_is_used_as_is():
    from google.adk.runners import Runner

    adk_agent = ScriptedAgent(name="scripted", script=[{"text": "ok"}], invocations=[])
    runner = Runner(app_name="custom", agent=adk_agent, session_service=InMemorySessionService())
    agent = GoogleADKAgent(name="Prebuilt", runner=runner)
    assert agent.run("q", session_id="s").content == "ok"
    assert asyncio.run(runner.session_service.get_session(app_name="custom", user_id="agno", session_id="s"))


def test_run_model_reports_the_root_llm_agent_model():
    from google.adk.agents import LlmAgent

    agent = GoogleADKAgent(name="Gemini", agent=LlmAgent(name="root", model="gemini-3.7-flash"))
    assert agent._run_model() == ("gemini-3.7-flash", "Google")
    assert GoogleADKAgent(name="None")._run_model() == (None, None)


def test_missing_agent_fails_at_run_time_not_construction():
    agent = GoogleADKAgent(name="Empty")
    assert agent.sdk == "google-adk"
    assert agent.run("q").status == RunStatus.error


def test_agentos_serves_streaming_and_non_streaming_runs(tmp_path):
    from fastapi.testclient import TestClient

    from agno.os import AgentOS

    agent, _ = _agent(TOOL_SCRIPT, db=SqliteDb(db_file=str(tmp_path / "runs.db")), name="ADK Assistant")
    with TestClient(AgentOS(agents=[agent]).get_app()) as client:
        listing = client.get("/agents")
        assert listing.status_code == 200
        assert listing.json()[0]["metadata"] == {"sdk": "google-adk"}

        response = client.post("/agents/adk-assistant/runs", data={"message": "weather?", "stream": "false"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["content"] == "It is sunny" and body["status"] == "COMPLETED"
        assert body["tools"][0]["tool_name"] == "get_weather"

        with client.stream(
            "POST", "/agents/adk-assistant/runs", data={"message": "weather?", "stream": "true", "session_id": "s"}
        ) as stream:
            assert stream.status_code == 200
            text = "".join(stream.iter_text())
        assert "RunStarted" in text and "ToolCallStarted" in text and "RunCompleted" in text
        assert text.count("It is sunny") >= 1
    assert agent.db.get_runs(session_id="s")[0].status == RunStatus.completed


def test_parallel_authors_keep_separate_stream_buffers():
    # Sub-agents of a ParallelAgent stream on their own branches, so their chunks interleave.
    script = [
        {"text": "Hel", "partial": True, "author": "a", "branch": "root.a"},
        {"text": "Wor", "partial": True, "author": "b", "branch": "root.b"},
        {"text": "lo", "partial": True, "author": "a", "branch": "root.a"},
        {"text": "ld", "partial": True, "author": "b", "branch": "root.b"},
        {"text": "Hello", "author": "a", "branch": "root.a"},
        {"text": "World", "author": "b", "branch": "root.b"},
    ]
    agent, _ = _agent(script)
    events = list(agent.run("go", stream=True))
    content = [event.content for event in events if isinstance(event, RunContentEvent)]
    # One source streams live; the other is held and emitted whole once the first is done.
    assert content == ["Hel", "lo", "\n\nWorld"]
    assert events[-1].content == "Hello\n\nWorld"
    # Without SSE mode ADK sends only the complete events.
    complete_only, _ = _agent([item for item in script if not item.get("partial")])
    assert complete_only.run("go").content == "Hello\n\nWorld"


def test_completed_tools_survive_a_failed_non_stream_attempt(tmp_path):
    script = TOOL_SCRIPT[:2] + [{"error_code": "RESOURCE_EXHAUSTED", "error_message": "quota"}]
    agent, _ = _agent(script, db=SqliteDb(db_file=str(tmp_path / "runs.db")))
    result = agent.run("weather?", session_id="s")
    assert result.status == RunStatus.error
    assert [(tool.tool_name, tool.result) for tool in result.tools or []] == [("get_weather", "sunny")]
    assert agent.db.get_runs(session_id="s")[0].tools[0].tool_name == "get_weather"


def test_held_source_that_completes_first_is_emitted_after_the_live_one():
    script = [
        {"text": "Hel", "partial": True, "author": "a"},
        {"text": "Wor", "partial": True, "author": "b"},
        {"text": "World", "author": "b"},
        {"text": "lo", "partial": True, "author": "a"},
        {"text": "Hello", "author": "a"},
        {"text": "Done", "author": "c"},
    ]
    agent, _ = _agent(script)
    events = list(agent.run("go", stream=True))
    assert [event.content for event in events if isinstance(event, RunContentEvent)] == [
        "Hel",
        "lo",
        "\n\nWorld",
        "\n\nDone",
    ]


def test_held_text_is_not_lost_when_the_invocation_ends_early():
    script = [
        {"text": "Hel", "partial": True, "author": "a"},
        {"text": "World", "partial": True, "author": "b"},
    ]
    agent, _ = _agent(script)
    result = list(agent.run("go", stream=True, yield_run_output=True))[-1]
    assert result.content == "Hel\n\nWorld"


def test_stale_native_session_is_rebuilt_from_stored_history(tmp_path):
    # Two AgentOS workers share the Agno database but each has its own in-memory ADK session service.
    db = SqliteDb(db_file=str(tmp_path / "runs.db"))
    worker_a, adk_a = _agent([{"text": "hi"}], db=db)
    worker_b, adk_b = _agent([{"text": "hi"}], db=db)
    worker_a.run("first", session_id="s1", user_id="u1")
    worker_b.run("second", session_id="s1", user_id="u1")
    assert "user: first" in adk_b.invocations[0].user_content.parts[0].text
    # Worker A's native session never saw turn 2, so it is rebuilt from the stored history.
    worker_a.run("third", session_id="s1", user_id="u1")
    prompt = adk_a.invocations[1].user_content.parts[0].text
    assert "user: first" in prompt and "user: second" in prompt and prompt.endswith("Current message:\nthird")
    native = asyncio.run(worker_a.session_service.get_session(app_name="agno", user_id="u1", session_id="s1"))
    assert native.state["agno_turns"] == 3
    assert len([event for event in native.events if event.author == "user"]) == 1
    # Now current again: the next turn on worker A resumes natively.
    worker_a.run("fourth", session_id="s1", user_id="u1")
    assert adk_a.invocations[2].user_content.parts[0].text == "fourth"


def test_uploaded_gemini_file_is_sent_by_uri():
    from types import SimpleNamespace

    uploaded = SimpleNamespace(
        uri="https://generativelanguage.googleapis.com/v1beta/files/abc", mime_type="application/pdf"
    )
    agent, adk_agent = _agent([{"text": "seen"}])
    assert agent.run("read", files=[File(external=uploaded)]).status == RunStatus.completed
    part = adk_agent.invocations[0].user_content.parts[1]
    assert (part.file_data.file_uri, part.file_data.mime_type) == (uploaded.uri, "application/pdf")


def test_remote_file_without_extension_keeps_the_served_content_type(monkeypatch):
    from agno.agents.google_adk import utils

    async def fake_download(url):
        assert url == "https://example.com/download?id=123"
        return b"%PDF-1.7", "application/pdf; charset=binary"

    monkeypatch.setattr(utils, "abytes_and_mime_from_url", fake_download)
    agent, adk_agent = _agent([{"text": "seen"}])
    assert agent.run("read", files=[File(url="https://example.com/download?id=123")]).status == RunStatus.completed
    part = adk_agent.invocations[0].user_content.parts[1]
    assert (part.inline_data.data, part.inline_data.mime_type) == (b"%PDF-1.7", "application/pdf")
