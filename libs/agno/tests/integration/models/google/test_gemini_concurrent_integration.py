import asyncio
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from agno.agent import Agent
from agno.models.google import Gemini
from agno.models.message import Message

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
pytestmark = pytest.mark.skipif(not GOOGLE_API_KEY, reason="GOOGLE_API_KEY not set")

PROMPT = "Say 'hello' and nothing else. Be very brief."
NUM_WORKERS = 8
NUM_REQUESTS = 16


class TestGeminiConcurrentSync:

    def test_concurrent_agent_run_no_ssl_errors(self):
        agent = Agent(model=Gemini(id="gemini-2.0-flash"))

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
        model = Gemini(id="gemini-2.0-flash")
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
        model = Gemini(id="gemini-2.0-flash")
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

    @pytest.mark.asyncio
    async def test_concurrent_agent_arun_no_ssl_errors(self):
        agent = Agent(model=Gemini(id="gemini-2.0-flash"))

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
        model = Gemini(id="gemini-2.0-flash")
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

    def test_concurrent_streaming_no_ssl_errors(self):
        agent = Agent(model=Gemini(id="gemini-2.0-flash"))

        results = {"success": 0, "ssl_errors": 0}
        lock = threading.Lock()

        def stream_response(_):
            try:
                response = agent.run(PROMPT, stream=True)
                content = response.content
                assert content is not None
                with lock:
                    results["success"] += 1
            except Exception as e:
                err_str = str(e).lower()
                with lock:
                    if "ssl" in err_str or "tls" in err_str:
                        results["ssl_errors"] += 1

        with ThreadPoolExecutor(max_workers=NUM_WORKERS) as pool:
            list(pool.map(stream_response, range(NUM_REQUESTS)))

        assert results["ssl_errors"] == 0, "SSL/TLS errors in streaming"

    @pytest.mark.asyncio
    async def test_concurrent_async_streaming_no_ssl_errors(self):
        agent = Agent(model=Gemini(id="gemini-2.0-flash"))

        results = {"success": 0, "ssl_errors": 0}

        async def stream_response():
            try:
                response = await agent.arun(PROMPT, stream=True)
                content = response.content
                assert content is not None
                results["success"] += 1
            except Exception as e:
                err_str = str(e).lower()
                if "ssl" in err_str or "tls" in err_str:
                    results["ssl_errors"] += 1

        tasks = [stream_response() for _ in range(NUM_REQUESTS)]
        await asyncio.gather(*tasks)

        assert results["ssl_errors"] == 0, "SSL/TLS errors in async streaming"


class TestGeminiMixedUsage:

    def test_sequential_sync_then_async_same_model(self):
        model = Gemini(id="gemini-2.0-flash")
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

    def test_high_concurrency_stress(self):
        agent = Agent(model=Gemini(id="gemini-2.0-flash"))

        stress_requests = 50
        stress_workers = 16

        results = {"success": 0, "ssl_errors": 0, "other_errors": 0}
        lock = threading.Lock()

        def run_agent(_):
            try:
                response = agent.run(PROMPT)
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
