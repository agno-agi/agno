import asyncio
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy

import pytest
from pydantic import BaseModel

from agno.agent import Agent
from agno.exceptions import ModelProviderError
from agno.models.google import Gemini
from agno.models.message import Message

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
pytestmark = pytest.mark.skipif(not GOOGLE_API_KEY, reason="GOOGLE_API_KEY not set")

PROMPT = "Say 'hello' and nothing else. Be very brief."
NUM_WORKERS = 8
NUM_REQUESTS = 16


def get_capital(country: str) -> str:
    """Return the capital city of the given country."""
    return {"France": "Paris", "Japan": "Tokyo"}.get(country, "Unknown")


class CityInfo(BaseModel):
    city: str
    country: str


class TestGeminiConcurrentSync:
    """Integration tests for concurrent synchronous Gemini usage."""

    def test_concurrent_agent_run_no_ssl_errors(self):
        """Verify concurrent agent.run() calls do not cause SSL/TLS errors."""
        agent = Agent(model=Gemini(id="gemini-flash-latest"))

        results = {"success": 0, "ssl_errors": 0, "other_errors": 0}
        errors = []
        lock = threading.Lock()

        def run_agent(_):
            try:
                response = agent.run(PROMPT)
                assert response.content is not None
                with lock:
                    results["success"] += 1
                return True
            except Exception as e:
                err_str = str(e).lower()
                with lock:
                    if "ssl" in err_str or "tls" in err_str or "decryption" in err_str:
                        results["ssl_errors"] += 1
                    else:
                        results["other_errors"] += 1
                    errors.append(str(e)[:100])
                return False

        with ThreadPoolExecutor(max_workers=NUM_WORKERS) as pool:
            futures = [pool.submit(run_agent, i) for i in range(NUM_REQUESTS)]
            for future in as_completed(futures):
                future.result()

        assert results["ssl_errors"] == 0, f"SSL/TLS errors detected: {errors}"
        assert results["success"] >= NUM_REQUESTS // 2, f"Too many failures: {errors}"

    def test_concurrent_model_response_no_ssl_errors(self):
        """Verify concurrent model.response() calls do not cause SSL/TLS errors."""
        model = Gemini(id="gemini-flash-latest")
        messages = [Message(role="user", content=PROMPT)]

        results = {"success": 0, "ssl_errors": 0}
        lock = threading.Lock()

        def call_response(_):
            try:
                response = model.response(messages=messages.copy())
                assert response.content is not None
                with lock:
                    results["success"] += 1
            except Exception as e:
                err_str = str(e).lower()
                with lock:
                    if "ssl" in err_str or "tls" in err_str:
                        results["ssl_errors"] += 1

        with ThreadPoolExecutor(max_workers=NUM_WORKERS) as pool:
            list(pool.map(call_response, range(NUM_REQUESTS)))

        assert results["ssl_errors"] == 0, "SSL/TLS errors in model.response()"

    def test_client_reused_across_concurrent_calls(self):
        """Verify the same client is reused across concurrent get_client() calls."""
        model = Gemini(id="gemini-flash-latest")
        client_ids = set()
        lock = threading.Lock()

        def get_client_id(_):
            client = model.get_client()
            with lock:
                client_ids.add(id(client))

        with ThreadPoolExecutor(max_workers=NUM_WORKERS) as pool:
            list(pool.map(get_client_id, range(NUM_REQUESTS)))

        assert len(client_ids) <= NUM_WORKERS, f"Too many clients created: {len(client_ids)}"


class TestGeminiConcurrentAsync:
    """Integration tests for concurrent asynchronous Gemini usage."""

    @pytest.mark.asyncio
    async def test_concurrent_agent_arun_no_ssl_errors(self):
        """Verify concurrent agent.arun() calls do not cause SSL/TLS errors."""
        agent = Agent(model=Gemini(id="gemini-flash-latest"))

        results = {"success": 0, "ssl_errors": 0, "other_errors": 0}
        errors = []

        async def run_agent():
            try:
                response = await agent.arun(PROMPT)
                assert response.content is not None
                results["success"] += 1
                return True
            except Exception as e:
                err_str = str(e).lower()
                if "ssl" in err_str or "tls" in err_str or "decryption" in err_str:
                    results["ssl_errors"] += 1
                else:
                    results["other_errors"] += 1
                errors.append(str(e)[:100])
                return False

        tasks = [run_agent() for _ in range(NUM_REQUESTS)]
        await asyncio.gather(*tasks)

        assert results["ssl_errors"] == 0, f"SSL/TLS errors in async: {errors}"
        assert results["success"] >= NUM_REQUESTS // 2, f"Too many async failures: {errors}"

    @pytest.mark.asyncio
    async def test_concurrent_model_aresponse_no_ssl_errors(self):
        """Verify concurrent model.aresponse() calls do not cause SSL/TLS errors."""
        model = Gemini(id="gemini-flash-latest")
        messages = [Message(role="user", content=PROMPT)]

        results = {"success": 0, "ssl_errors": 0}

        async def call_aresponse():
            try:
                response = await model.aresponse(messages=messages.copy())
                assert response.content is not None
                results["success"] += 1
            except Exception as e:
                err_str = str(e).lower()
                if "ssl" in err_str or "tls" in err_str:
                    results["ssl_errors"] += 1

        tasks = [call_aresponse() for _ in range(NUM_REQUESTS)]
        await asyncio.gather(*tasks)

        assert results["ssl_errors"] == 0, "SSL/TLS errors in model.aresponse()"


class TestGeminiConcurrentStreaming:
    """Integration tests for concurrent streaming Gemini usage."""

    def test_concurrent_streaming_no_ssl_errors(self):
        """Verify concurrent streaming requests drain fully without SSL/TLS errors."""
        agent = Agent(model=Gemini(id="gemini-flash-latest"))

        results = {"success": 0, "ssl_errors": 0, "other_errors": 0}
        errors = []
        lock = threading.Lock()

        def stream_response(_):
            try:
                events = list(agent.run(PROMPT, stream=True))
                assert len(events) > 0
                with lock:
                    results["success"] += 1
            except Exception as e:
                err_str = str(e).lower()
                with lock:
                    if "ssl" in err_str or "tls" in err_str:
                        results["ssl_errors"] += 1
                    else:
                        results["other_errors"] += 1
                    errors.append(str(e)[:100])

        with ThreadPoolExecutor(max_workers=NUM_WORKERS) as pool:
            list(pool.map(stream_response, range(NUM_REQUESTS)))

        assert results["ssl_errors"] == 0, f"SSL/TLS errors in streaming: {errors}"
        assert results["success"] >= NUM_REQUESTS // 2, f"Too many streaming failures: {errors}"

    @pytest.mark.asyncio
    async def test_concurrent_async_streaming_no_ssl_errors(self):
        """Verify concurrent async streaming requests drain fully without SSL/TLS errors."""
        agent = Agent(model=Gemini(id="gemini-flash-latest"))

        results = {"success": 0, "ssl_errors": 0, "other_errors": 0}
        errors = []

        async def stream_response():
            try:
                events = [event async for event in agent.arun(PROMPT, stream=True)]
                assert len(events) > 0
                results["success"] += 1
            except Exception as e:
                err_str = str(e).lower()
                if "ssl" in err_str or "tls" in err_str:
                    results["ssl_errors"] += 1
                else:
                    results["other_errors"] += 1
                errors.append(str(e)[:100])

        tasks = [stream_response() for _ in range(NUM_REQUESTS)]
        await asyncio.gather(*tasks)

        assert results["ssl_errors"] == 0, f"SSL/TLS errors in async streaming: {errors}"
        assert results["success"] >= NUM_REQUESTS // 2, f"Too many async streaming failures: {errors}"


class TestGeminiMixedUsage:
    """Integration tests for mixed sync/async Gemini usage patterns."""

    def test_sequential_sync_then_async_same_model(self):
        """Verify client persists when switching between sync and async calls."""
        model = Gemini(id="gemini-flash-latest")
        messages = [Message(role="user", content=PROMPT)]

        response1 = model.response(messages=messages.copy())
        assert response1.content is not None
        client_id_1 = id(model.client)

        async def async_call():
            return await model.aresponse(messages=messages.copy())

        response2 = asyncio.run(async_call())
        assert response2.content is not None
        client_id_2 = id(model.client)

        response3 = model.response(messages=messages.copy())
        assert response3.content is not None
        client_id_3 = id(model.client)

        assert client_id_1 == client_id_2 == client_id_3, "Client changed unexpectedly"


class TestGeminiStressTest:
    """Stress tests for high-concurrency Gemini usage."""

    def test_high_concurrency_stress(self):
        """Verify no SSL/TLS errors under high concurrent load (50 requests, 16 workers)."""
        agent = Agent(model=Gemini(id="gemini-flash-latest"))

        stress_requests = 50
        stress_workers = 16

        results = {"success": 0, "ssl_errors": 0, "other_errors": 0}
        lock = threading.Lock()

        def run_agent(_):
            try:
                agent.run(PROMPT)
                with lock:
                    results["success"] += 1
            except Exception as e:
                err_str = str(e).lower()
                with lock:
                    if "ssl" in err_str or "tls" in err_str or "decryption" in err_str:
                        results["ssl_errors"] += 1
                    else:
                        results["other_errors"] += 1

        with ThreadPoolExecutor(max_workers=stress_workers) as pool:
            list(pool.map(run_agent, range(stress_requests)))

        assert results["ssl_errors"] == 0, "SSL/TLS errors under stress"
        assert results["success"] >= stress_requests * 0.5, "Too many failures under stress"


class TestGeminiCrossEventLoop:
    """Integration tests for client reuse across separate asyncio event loops.

    Production pattern: scripts, notebooks, and schedulers call asyncio.run()
    repeatedly on the same long-lived model instance. The cached client's async
    transports must survive event-loop turnover.
    """

    def test_aresponse_across_two_event_loops(self):
        """Verify a second asyncio.run() reuses the cached client without dead-loop errors."""
        model = Gemini(id="gemini-flash-latest")
        messages = [Message(role="user", content=PROMPT)]

        response1 = asyncio.run(model.aresponse(messages=messages.copy()))
        assert response1.content is not None
        client_id = id(model.client)

        response2 = asyncio.run(model.aresponse(messages=messages.copy()))
        assert response2.content is not None
        assert id(model.client) == client_id, "Client was recreated between event loops"

    def test_async_streaming_across_two_event_loops(self):
        """Verify async streaming works in a fresh event loop on a cached client."""
        agent = Agent(model=Gemini(id="gemini-flash-latest"))

        async def stream_once():
            return [event async for event in agent.arun(PROMPT, stream=True)]

        events1 = asyncio.run(stream_once())
        events2 = asyncio.run(stream_once())
        assert len(events1) > 0, "First event loop produced no stream events"
        assert len(events2) > 0, "Second event loop produced no stream events"


class TestGeminiToolCalling:
    """Integration tests for tool-calling loops on a shared cached client.

    A tool-call run makes multiple model invocations (request, tool execution,
    continuation) through the same client mid-run.
    """

    def test_concurrent_tool_calling(self):
        """Verify concurrent runs with tool-call continuations share one client safely."""
        agent = Agent(model=Gemini(id="gemini-flash-latest"), tools=[get_capital])

        results = {"success": 0, "ssl_errors": 0, "other_errors": 0}
        errors = []
        lock = threading.Lock()

        def run_agent(_):
            try:
                response = agent.run("Use the get_capital tool to find the capital of France.")
                assert response.content is not None
                with lock:
                    results["success"] += 1
            except Exception as e:
                err_str = str(e).lower()
                with lock:
                    if "ssl" in err_str or "tls" in err_str:
                        results["ssl_errors"] += 1
                    else:
                        results["other_errors"] += 1
                    errors.append(str(e)[:100])

        with ThreadPoolExecutor(max_workers=NUM_WORKERS) as pool:
            list(pool.map(run_agent, range(NUM_WORKERS)))

        assert results["ssl_errors"] == 0, f"SSL/TLS errors in tool calling: {errors}"
        assert results["success"] >= NUM_WORKERS // 2, f"Too many tool-calling failures: {errors}"

    @pytest.mark.asyncio
    async def test_async_streaming_tool_calling(self):
        """Verify async streaming with tool-call continuations completes on a shared client."""
        agent = Agent(model=Gemini(id="gemini-flash-latest"), tools=[get_capital])

        events = [
            event async for event in agent.arun("Use the get_capital tool to find the capital of Japan.", stream=True)
        ]
        assert len(events) > 0, "Streaming tool-call run produced no events"
        content = "".join(getattr(event, "content", None) or "" for event in events)
        assert content, "Streaming tool-call run produced no content"


class TestGeminiClientResilience:
    """Integration tests for client survival across errors and interrupted streams."""

    def test_interrupted_stream_then_reuse(self):
        """Verify abandoning a stream mid-iteration does not poison the cached client."""
        agent = Agent(model=Gemini(id="gemini-flash-latest"))

        stream = agent.run("Count from 1 to 50, one number per line.", stream=True)
        chunks = 0
        for _event in stream:
            chunks += 1
            if chunks >= 3:
                break

        response = agent.run(PROMPT)
        assert response.content is not None

    def test_error_then_recovery_same_client(self):
        """Verify a failed request does not poison the cached client for later requests."""
        model = Gemini(id="gemini-flash-latest")
        messages = [Message(role="user", content=PROMPT)]

        response1 = model.response(messages=messages.copy())
        assert response1.content is not None
        client_before = model.client

        model.id = "gemini-nonexistent-model-for-test"
        with pytest.raises(ModelProviderError):
            model.response(messages=messages.copy())

        model.id = "gemini-flash-latest"
        response2 = model.response(messages=messages.copy())
        assert response2.content is not None
        assert model.client is client_before, "Client was recreated after error"

    def test_sustained_sequential_runs_single_client(self):
        """Verify one client instance serves many sequential runs."""
        model = Gemini(id="gemini-flash-latest")
        messages = [Message(role="user", content=PROMPT)]

        client_ids = set()
        for _ in range(6):
            response = model.response(messages=messages.copy())
            assert response.content is not None
            client_ids.add(id(model.client))

        assert len(client_ids) == 1, f"Client churned across sequential runs: {len(client_ids)} instances"


class TestGeminiStructuredOutput:
    """Integration tests for structured output on a shared cached client."""

    def test_concurrent_structured_output(self):
        """Verify concurrent structured-output runs share one client safely."""
        agent = Agent(model=Gemini(id="gemini-flash-latest"), output_schema=CityInfo)

        results = {"success": 0, "errors": 0}
        errors = []
        lock = threading.Lock()

        def run_agent(_):
            try:
                response = agent.run("What is the capital of France? Reply with the city and country.")
                assert isinstance(response.content, CityInfo)
                with lock:
                    results["success"] += 1
            except Exception as e:
                with lock:
                    results["errors"] += 1
                    errors.append(str(e)[:100])

        with ThreadPoolExecutor(max_workers=NUM_WORKERS) as pool:
            list(pool.map(run_agent, range(NUM_WORKERS)))

        assert results["success"] >= NUM_WORKERS // 2, f"Structured output failures: {errors}"


class TestGeminiModelCopies:
    """Integration tests for deepcopy'd models building independent clients.

    Teams deep-copy models in production (e.g. reasoning models); copies must
    not inherit the live client and must not disturb the original's client.
    """

    def test_deepcopy_gets_independent_client(self):
        """Verify a deepcopy starts clientless, builds its own client, and leaves the original intact."""
        model = Gemini(id="gemini-flash-latest")
        messages = [Message(role="user", content=PROMPT)]

        response1 = model.response(messages=messages.copy())
        assert response1.content is not None
        original_client = model.client
        assert original_client is not None

        model_copy = deepcopy(model)
        assert model_copy.client is None, "Copy must not inherit the live client"

        response2 = model_copy.response(messages=messages.copy())
        assert response2.content is not None
        assert model_copy.client is not original_client, "Copy must build its own client"
        assert model.client is original_client, "Original client must be untouched"


class TestGeminiThoughtSignatures:
    """Integration tests for Gemini 3 thought-signature round-trips on a cached client.

    Thought signatures shipped alongside the per-response client cleanup
    (PR #5454). They are message-level state and must survive its removal:
    a tool-call continuation echoes the signature back to the API.
    """

    def test_tool_call_with_thought_signatures(self):
        """Verify a Gemini 3 tool-call round-trip completes on a cached client."""
        agent = Agent(model=Gemini(id="gemini-3-flash-preview"), tools=[get_capital])

        try:
            response = agent.run("Use the get_capital tool to find the capital of France.")
        except ModelProviderError as e:
            if "404" in str(e) or "NOT_FOUND" in str(e):
                pytest.skip("gemini-3-flash-preview not available for this API key")
            raise

        assert response.content is not None
        tool_messages = [m for m in (response.messages or []) if m.role == "tool"]
        assert tool_messages, "Tool was not executed"
