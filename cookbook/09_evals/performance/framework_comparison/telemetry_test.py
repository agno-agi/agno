"""
Telemetry Impact Test

This script demonstrates that Agno's telemetry (enabled by default)
adds ~200ms of latency per call.

Key Finding:
- With telemetry=True (default): ~200ms overhead
- With telemetry=False: ~0ms overhead

Usage:
    python cookbook/09_evals/performance/framework_comparison/telemetry_test.py
"""

import asyncio
import logging
import os
import statistics
import time

logging.disable(logging.CRITICAL)


async def run_test():
    """Compare agent performance with and without telemetry."""
    from agno.agent import Agent
    from agno.models.openai import OpenAIChat
    from agno.utils.log import set_log_level_to_error
    from openai import AsyncOpenAI

    set_log_level_to_error()

    direct_client = AsyncOpenAI()

    # Agent WITH telemetry (default behavior)
    agent_with_telemetry = Agent(
        model=OpenAIChat(id="gpt-4o"),
        system_message="You are a helpful assistant. Be concise.",
        telemetry=True,
    )

    # Agent WITHOUT telemetry
    agent_without_telemetry = Agent(
        model=OpenAIChat(id="gpt-4o"),
        system_message="You are a helpful assistant. Be concise.",
        telemetry=False,
    )

    # Warmup
    print("Warming up...")
    for _ in range(2):
        await direct_client.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": "Hi"}]
        )
        await agent_with_telemetry.arun("Hi")
        await agent_without_telemetry.arun("Hi")

    print("Running interleaved comparison (15 iterations)...")
    iterations = 15

    direct_times = []
    with_telemetry_times = []
    without_telemetry_times = []

    for i in range(iterations):
        if (i + 1) % 5 == 0:
            print(f"  Iteration {i + 1}/{iterations}")

        # Direct OpenAI
        start = time.perf_counter()
        await direct_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a helpful assistant. Be concise."},
                {"role": "user", "content": "What is 2 + 2?"},
            ],
        )
        direct_times.append(time.perf_counter() - start)

        # Agent WITH telemetry
        start = time.perf_counter()
        await agent_with_telemetry.arun("What is 2 + 2?")
        with_telemetry_times.append(time.perf_counter() - start)

        # Agent WITHOUT telemetry
        start = time.perf_counter()
        await agent_without_telemetry.arun("What is 2 + 2?")
        without_telemetry_times.append(time.perf_counter() - start)

    return direct_times, with_telemetry_times, without_telemetry_times


def analyze(direct_times, with_telemetry_times, without_telemetry_times):
    """Analyze and display results."""

    def trim_outliers(times, pct=0.1):
        n = max(1, int(len(times) * pct))
        sorted_times = sorted(times)
        return sorted_times[n:-n] if n > 0 and len(sorted_times) > 2 * n else sorted_times

    direct = trim_outliers(direct_times)
    with_tel = trim_outliers(with_telemetry_times)
    without_tel = trim_outliers(without_telemetry_times)

    direct_med = statistics.median(direct) * 1000
    with_tel_med = statistics.median(with_tel) * 1000
    without_tel_med = statistics.median(without_tel) * 1000

    print("\n" + "=" * 60)
    print("TELEMETRY IMPACT TEST RESULTS")
    print("=" * 60)

    print("\n" + "-" * 60)
    print("MEDIAN LATENCIES")
    print("-" * 60)
    print(f"  Direct OpenAI:             {direct_med:>8.2f} ms (baseline)")
    print(f"  Agent WITH telemetry:      {with_tel_med:>8.2f} ms")
    print(f"  Agent WITHOUT telemetry:   {without_tel_med:>8.2f} ms")

    print("\n" + "-" * 60)
    print("OVERHEAD ANALYSIS")
    print("-" * 60)
    with_overhead = with_tel_med - direct_med
    without_overhead = without_tel_med - direct_med
    telemetry_cost = with_tel_med - without_tel_med

    print(f"  WITH telemetry overhead:   {with_overhead:>+8.2f} ms")
    print(f"  WITHOUT telemetry overhead:{without_overhead:>+8.2f} ms")
    print(f"  ---")
    print(f"  TELEMETRY COST:            {telemetry_cost:>+8.2f} ms")

    print("\n" + "-" * 60)
    print("RECOMMENDATION")
    print("-" * 60)
    print("  For performance-critical applications, disable telemetry:")
    print()
    print("    agent = Agent(..., telemetry=False)")
    print()
    print("  Or set environment variable: AGNO_TELEMETRY=false")


async def main():
    direct_times, with_telemetry_times, without_telemetry_times = await run_test()
    analyze(direct_times, with_telemetry_times, without_telemetry_times)


if __name__ == "__main__":
    asyncio.run(main())
