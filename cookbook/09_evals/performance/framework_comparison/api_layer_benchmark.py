"""
API Layer Performance Benchmark

Compares the overhead of different API layers:
1. Direct OpenAI call (baseline)
2. Direct Agent call (no HTTP)
3. Barebones FastAPI + Agent
4. AgentOS API

Prerequisites:
    1. Start the servers (in separate terminals):
       python cookbook/09_evals/performance/framework_comparison/servers/fastapi_server.py
       python cookbook/09_evals/performance/framework_comparison/servers/agentos_server.py

    2. Run this benchmark:
       python cookbook/09_evals/performance/framework_comparison/api_layer_benchmark.py

Key Findings:
    - Basic HTTP layer (FastAPI): ~60ms overhead
    - AgentOS vs barebones FastAPI: ~20ms additional overhead
    - Total AgentOS overhead: ~80ms (worth it for enterprise features)
"""

import asyncio
import logging
import os
import statistics
import time

logging.disable(logging.CRITICAL)
os.environ["AGNO_TELEMETRY"] = "false"

import httpx

FASTAPI_URL = "http://localhost:7779"
AGENTOS_URL = "http://localhost:7778"
AGENT_ID = "benchmark-agent"


async def check_servers():
    """Check if servers are running."""
    results = {}
    async with httpx.AsyncClient() as client:
        for name, url in [("fastapi", FASTAPI_URL), ("agentos", AGENTOS_URL)]:
            try:
                response = await client.get(f"{url}/health", timeout=5.0)
                results[name] = response.status_code == 200
            except Exception:
                results[name] = False
    return results


async def direct_openai_call(client, message: str) -> float:
    start = time.perf_counter()
    await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a helpful assistant. Be concise."},
            {"role": "user", "content": message},
        ],
    )
    return time.perf_counter() - start


async def direct_agent_call(agent, message: str) -> float:
    start = time.perf_counter()
    await agent.arun(message)
    return time.perf_counter() - start


async def fastapi_call(client: httpx.AsyncClient, message: str) -> float:
    start = time.perf_counter()
    await client.post(f"{FASTAPI_URL}/agent/run", data={"message": message}, timeout=60.0)
    return time.perf_counter() - start


async def agentos_call(client: httpx.AsyncClient, message: str) -> float:
    start = time.perf_counter()
    await client.post(
        f"{AGENTOS_URL}/agents/{AGENT_ID}/runs",
        data={"message": message, "stream": "false"},
        timeout=60.0,
    )
    return time.perf_counter() - start


async def run_benchmark():
    from agno.agent import Agent
    from agno.models.openai import OpenAIChat
    from agno.utils.log import set_log_level_to_error
    from openai import AsyncOpenAI

    set_log_level_to_error()

    print("Checking servers...")
    status = await check_servers()

    if not status["fastapi"]:
        print(f"\nWarning: FastAPI server not running at {FASTAPI_URL}")
        print("  Start: python .../servers/fastapi_server.py")

    if not status["agentos"]:
        print(f"\nWarning: AgentOS server not running at {AGENTOS_URL}")
        print("  Start: python .../servers/agentos_server.py")

    if not status["fastapi"] and not status["agentos"]:
        print("\nNo servers running. Please start at least one server.")
        return None

    # Setup
    openai_client = AsyncOpenAI()
    http_client = httpx.AsyncClient()
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        system_message="You are a helpful assistant. Be concise.",
        telemetry=False,
    )

    # Warmup
    print("\nWarming up...")
    for _ in range(2):
        await direct_openai_call(openai_client, "Hi")
        await direct_agent_call(agent, "Hi")
        if status["fastapi"]:
            await fastapi_call(http_client, "Hi")
        if status["agentos"]:
            await agentos_call(http_client, "Hi")

    # Benchmark
    print("Running interleaved benchmark (15 iterations)...")
    iterations = 15

    results = {
        "openai": [],
        "agent": [],
        "fastapi": [],
        "agentos": [],
    }

    for i in range(iterations):
        if (i + 1) % 5 == 0:
            print(f"  Iteration {i + 1}/{iterations}")

        results["openai"].append(await direct_openai_call(openai_client, "What is 2 + 2?"))
        results["agent"].append(await direct_agent_call(agent, "What is 2 + 2?"))
        if status["fastapi"]:
            results["fastapi"].append(await fastapi_call(http_client, "What is 2 + 2?"))
        if status["agentos"]:
            results["agentos"].append(await agentos_call(http_client, "What is 2 + 2?"))

    await http_client.aclose()
    return results, status


def analyze(results, status):
    def trim_outliers(times, pct=0.1):
        if not times:
            return []
        n = max(1, int(len(times) * pct))
        return sorted(times)[n:-n] if len(times) > 2 * n else times

    def med(times):
        return statistics.median(times) * 1000 if times else 0

    openai_med = med(trim_outliers(results["openai"]))
    agent_med = med(trim_outliers(results["agent"]))
    fastapi_med = med(trim_outliers(results["fastapi"]))
    agentos_med = med(trim_outliers(results["agentos"]))

    print("\n" + "=" * 60)
    print("API LAYER PERFORMANCE BENCHMARK")
    print("=" * 60)

    print("\n" + "-" * 60)
    print("MEDIAN LATENCIES")
    print("-" * 60)
    print(f"  Direct OpenAI:        {openai_med:>8.2f} ms (baseline)")
    print(f"  Direct Agent:         {agent_med:>8.2f} ms ({agent_med/openai_med:.2f}x)")
    if status["fastapi"]:
        print(f"  FastAPI + Agent:      {fastapi_med:>8.2f} ms ({fastapi_med/openai_med:.2f}x)")
    if status["agentos"]:
        print(f"  AgentOS API:          {agentos_med:>8.2f} ms ({agentos_med/openai_med:.2f}x)")

    print("\n" + "-" * 60)
    print("HTTP LAYER OVERHEAD (vs Direct Agent)")
    print("-" * 60)
    print(f"  Agent framework:      {agent_med - openai_med:>+8.2f} ms")
    if status["fastapi"]:
        print(f"  Barebones FastAPI:    {fastapi_med - agent_med:>+8.2f} ms")
    if status["agentos"]:
        print(f"  AgentOS HTTP layer:   {agentos_med - agent_med:>+8.2f} ms")

    if status["fastapi"] and status["agentos"]:
        diff = agentos_med - fastapi_med
        print("\n" + "-" * 60)
        print("AGENTOS vs BAREBONES FASTAPI")
        print("-" * 60)
        print(f"  AgentOS overhead:     {diff:>+8.2f} ms")
        print(f"\n  This overhead provides: sessions, memory, RBAC, multi-agent, etc.")


async def main():
    result = await run_benchmark()
    if result:
        results, status = result
        analyze(results, status)


if __name__ == "__main__":
    asyncio.run(main())
