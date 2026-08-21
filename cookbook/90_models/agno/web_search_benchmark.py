"""
Agno Gateway web search vs SDK DuckDuckGo benchmark
====================================================

Measures end-to-end tool latency without involving an LLM. The Gateway sample
uses the same ``AgnoTools`` entrypoint an Agent uses; the local sample calls
``DuckDuckGoTools.web_search`` in a worker thread because it is synchronous.

This is a user-path benchmark, not an isolated MCP transport benchmark. The two
implementations can use different network paths and DuckDuckGo request logic. Some
``ddgs`` releases disable their DuckDuckGo text backend when it is heavily rate-limited
and fall back to other search engines; that fallback is part of the SDK behavior being
measured. Failures and throttling are reported instead of being discarded.

Requires:
- AGNO_API_KEY
- A reachable Gateway MCP endpoint (set AGNO_GATEWAY_MCP_URL for local/staging)
- ``mcp`` and ``ddgs`` (``uv pip install -U mcp ddgs``)

Each successful Gateway call is normal hosted-tool usage and may be billable.

Example:
    python cookbook/90_models/agno/web_search_benchmark.py \
        --query "latest developments in AI agents" --runs 10 --delay 1
"""

import argparse
import asyncio
import inspect
import json
import math
import statistics
from dataclasses import dataclass
from functools import partial
from time import perf_counter
from typing import Awaitable, Callable

from agno.tools.agno import AgnoTools
from agno.tools.duckduckgo import DuckDuckGoTools


@dataclass
class Sample:
    backend: str
    latency_seconds: float
    output_bytes: int = 0
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


async def call_gateway(entrypoint: Callable[..., object], query: str, max_results: int) -> str:
    result = entrypoint(query=query, max_results=max_results)
    if inspect.isawaitable(result):
        result = await result

    content = getattr(result, "content", None)
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Gateway returned an empty web-search result")
    if content.startswith(("Error:", "Error from MCP tool", "No results found")):
        raise RuntimeError(content)
    return content


async def call_sdk_duckduckgo(tool: DuckDuckGoTools, query: str, max_results: int) -> str:
    content = await asyncio.to_thread(tool.web_search, query=query, max_results=max_results)
    parsed = json.loads(content)
    if not isinstance(parsed, list) or not parsed:
        raise RuntimeError("DuckDuckGoTools returned no usable results")
    return content


async def measure(
    backend: str,
    operation: Callable[[], Awaitable[str]],
) -> Sample:
    started = perf_counter()
    try:
        output = await operation()
        return Sample(
            backend=backend,
            latency_seconds=perf_counter() - started,
            output_bytes=len(output.encode("utf-8")),
        )
    except Exception as exc:
        return Sample(
            backend=backend,
            latency_seconds=perf_counter() - started,
            error=f"{type(exc).__name__}: {exc}",
        )


def percentile(values: list[float], percentile_value: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile_value * len(ordered)) - 1)
    return ordered[index]


def print_summary(samples: list[Sample]) -> None:
    print("\nEnd-to-end search latency (seconds)")
    print("backend       ok/total  median     p95    mean     min     max  avg bytes")
    print("------------  --------  ------  ------  ------  ------  ------  ---------")

    for backend in ("gateway_mcp", "sdk_duckduckgo"):
        backend_samples = [sample for sample in samples if sample.backend == backend]
        successful = [sample for sample in backend_samples if sample.succeeded]
        if not successful:
            print(f"{backend:<12}  0/{len(backend_samples):<7}  no successful samples")
            continue

        latencies = [sample.latency_seconds for sample in successful]
        average_bytes = statistics.fmean(sample.output_bytes for sample in successful)
        print(
            f"{backend:<12}  {len(successful)}/{len(backend_samples):<7}  "
            f"{statistics.median(latencies):>6.3f}  "
            f"{percentile(latencies, 0.95):>6.3f}  "
            f"{statistics.fmean(latencies):>6.3f}  "
            f"{min(latencies):>6.3f}  "
            f"{max(latencies):>6.3f}  "
            f"{average_bytes:>9.0f}"
        )

    failures = [sample for sample in samples if not sample.succeeded]
    if failures:
        print("\nFailures and throttling")
        for sample in failures:
            print(f"- {sample.backend} after {sample.latency_seconds:.3f}s: {sample.error}")


async def benchmark(args: argparse.Namespace) -> None:
    duckduckgo = DuckDuckGoTools(enable_news=False, fixed_max_results=args.max_results)

    setup_started = perf_counter()
    async with AgnoTools(include_tools=["web_search"]) as agno_tools:
        setup_seconds = perf_counter() - setup_started
        gateway_function = agno_tools.functions.get("web_search")
        if gateway_function is None or gateway_function.entrypoint is None:
            raise RuntimeError("Gateway did not advertise the web_search tool")

        gateway_call = partial(
            call_gateway,
            gateway_function.entrypoint,
            args.query,
            args.max_results,
        )
        duckduckgo_call = partial(
            call_sdk_duckduckgo,
            duckduckgo,
            args.query,
            args.max_results,
        )

        print(f"Gateway MCP setup and tools/list: {setup_seconds:.3f}s")
        print(
            f"Benchmarking {args.runs} measured runs per backend "
            f"after {args.warmups} warm-up run(s)."
        )

        for _ in range(args.warmups):
            await measure("gateway_mcp", gateway_call)
            await asyncio.sleep(args.delay)
            await measure("sdk_duckduckgo", duckduckgo_call)
            await asyncio.sleep(args.delay)

        samples: list[Sample] = []
        for run_index in range(args.runs):
            operations = [
                ("gateway_mcp", gateway_call),
                ("sdk_duckduckgo", duckduckgo_call),
            ]
            if run_index % 2:
                operations.reverse()

            for backend, operation in operations:
                sample = await measure(backend, operation)
                samples.append(sample)
                status = "ok" if sample.succeeded else "failed"
                print(f"run {run_index + 1:>2}  {backend:<14}  {sample.latency_seconds:>7.3f}s  {status}")
                await asyncio.sleep(args.delay)

    print_summary(samples)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare hosted Agno MCP web search with the SDK DuckDuckGo tool."
    )
    parser.add_argument("--query", default="latest developments in AI agents")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--max-results", type=int, default=5)
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay between requests to reduce self-induced throttling.",
    )
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    if args.warmups < 0:
        parser.error("--warmups cannot be negative")
    if args.max_results < 1:
        parser.error("--max-results must be at least 1")
    if args.delay < 0:
        parser.error("--delay cannot be negative")
    return args


if __name__ == "__main__":
    asyncio.run(benchmark(parse_args()))
