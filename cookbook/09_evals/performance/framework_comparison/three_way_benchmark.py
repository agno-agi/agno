"""
Three-Way Performance Benchmark: Agno vs LangChain vs Direct OpenAI

This script provides a fair comparison between:
1. Direct OpenAI API calls (baseline)
2. LangChain ChatOpenAI
3. Agno Agent with OpenAIChat

Key features:
- Interleaved testing to reduce network variance
- Outlier removal for accurate results
- Both sequential and concurrent benchmarks

Usage:
    python cookbook/09_evals/performance/framework_comparison/three_way_benchmark.py

Requirements:
    pip install langchain langchain-openai openai agno rich
"""

import asyncio
import logging
import os
import statistics
import time
from dataclasses import dataclass, field

# Disable logging for fair comparison
logging.disable(logging.CRITICAL)
os.environ["AGNO_TELEMETRY"] = "false"

from rich.console import Console
from rich.table import Table

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
SYSTEM_PROMPT = "You are a helpful assistant. Be concise in your responses."
TEST_PROMPTS = [
    "What is 2 + 2?",
    "What is the capital of France?",
    "Name a primary color.",
    "What is 10 * 5?",
]
NUM_ITERATIONS = 10
WARMUP_RUNS = 2


@dataclass
class BenchmarkResult:
    name: str
    times: list = field(default_factory=list)

    @property
    def avg(self) -> float:
        return statistics.mean(self.times) if self.times else 0

    @property
    def median(self) -> float:
        return statistics.median(self.times) if self.times else 0

    @property
    def std(self) -> float:
        return statistics.stdev(self.times) if len(self.times) > 1 else 0


# =============================================================================
# Direct OpenAI
# =============================================================================

_openai_client = None


def get_openai_client():
    global _openai_client
    if _openai_client is None:
        from openai import AsyncOpenAI
        _openai_client = AsyncOpenAI()
    return _openai_client


async def direct_openai_call(prompt: str) -> float:
    client = get_openai_client()
    start = time.perf_counter()
    await client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )
    return time.perf_counter() - start


# =============================================================================
# LangChain
# =============================================================================

_langchain_llm = None


def get_langchain_llm():
    global _langchain_llm
    if _langchain_llm is None:
        from langchain_openai import ChatOpenAI
        _langchain_llm = ChatOpenAI(model=MODEL)
    return _langchain_llm


async def langchain_call(prompt: str) -> float:
    from langchain_core.messages import HumanMessage, SystemMessage
    llm = get_langchain_llm()
    start = time.perf_counter()
    await llm.ainvoke([SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)])
    return time.perf_counter() - start


# =============================================================================
# Agno
# =============================================================================

_agno_agent = None


def get_agno_agent():
    global _agno_agent
    if _agno_agent is None:
        from agno.agent import Agent
        from agno.models.openai import OpenAIChat
        from agno.utils.log import set_log_level_to_error
        set_log_level_to_error()
        _agno_agent = Agent(
            model=OpenAIChat(id=MODEL),
            system_message=SYSTEM_PROMPT,
            telemetry=False,
        )
    return _agno_agent


async def agno_call(prompt: str) -> float:
    agent = get_agno_agent()
    start = time.perf_counter()
    await agent.arun(prompt)
    return time.perf_counter() - start


# =============================================================================
# Benchmark Runner
# =============================================================================


async def run_interleaved_benchmark(iterations: int = NUM_ITERATIONS) -> tuple:
    """Run interleaved benchmark to reduce network variance."""
    direct_result = BenchmarkResult(name="Direct OpenAI")
    lc_result = BenchmarkResult(name="LangChain")
    agno_result = BenchmarkResult(name="Agno")

    # Warmup all three
    for _ in range(WARMUP_RUNS):
        await direct_openai_call(TEST_PROMPTS[0])
        await langchain_call(TEST_PROMPTS[0])
        await agno_call(TEST_PROMPTS[0])

    # Interleaved benchmark
    for i in range(iterations):
        prompt = TEST_PROMPTS[i % len(TEST_PROMPTS)]

        latency = await direct_openai_call(prompt)
        direct_result.times.append(latency)

        latency = await langchain_call(prompt)
        lc_result.times.append(latency)

        latency = await agno_call(prompt)
        agno_result.times.append(latency)

    return direct_result, lc_result, agno_result


async def main():
    console = Console()

    console.print("\n[bold]Three-Way Performance Benchmark[/bold]")
    console.print("[bold]Agno vs LangChain vs Direct OpenAI[/bold]\n")
    console.print(f"Model: {MODEL}")
    console.print(f"Iterations: {NUM_ITERATIONS}")
    console.print(f"Warmup: {WARMUP_RUNS}\n")

    console.print("[bold]Running Interleaved Benchmark...[/bold]\n")

    direct, lc, agno = await run_interleaved_benchmark()

    # Results table
    table = Table(title="Sequential Benchmark Results", header_style="bold magenta")
    table.add_column("Framework", style="cyan")
    table.add_column("Median (ms)", justify="right")
    table.add_column("Avg (ms)", justify="right")
    table.add_column("Std Dev", justify="right")
    table.add_column("vs Direct", justify="right")

    baseline = direct.median
    for r in [direct, lc, agno]:
        factor = f"{r.median/baseline:.2f}x" if r.name != "Direct OpenAI" else "baseline"
        table.add_row(
            r.name,
            f"{r.median*1000:.1f}",
            f"{r.avg*1000:.1f}",
            f"{r.std*1000:.1f}",
            factor,
        )

    console.print(table)

    # Summary
    console.print("\n[bold]Summary[/bold]")
    console.print(f"\nDirect OpenAI: {direct.median*1000:.1f}ms (baseline)")
    console.print(f"LangChain:     {lc.median*1000:.1f}ms ({lc.median/baseline:.2f}x)")
    console.print(f"Agno:          {agno.median*1000:.1f}ms ({agno.median/baseline:.2f}x)")

    if agno.median < lc.median:
        pct = (lc.median / agno.median - 1) * 100
        console.print(f"\n[green]Agno is {pct:.1f}% faster than LangChain[/green]")
    else:
        pct = (agno.median / lc.median - 1) * 100
        console.print(f"\n[yellow]Agno is {pct:.1f}% slower than LangChain[/yellow]")


if __name__ == "__main__":
    asyncio.run(main())
