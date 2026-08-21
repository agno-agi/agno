"""
Shared Benchmark Harness
========================

Shared pieces for the Agno performance benchmark suite:

- MockModel / MockToolModel: in-process models that drive the full run loop
  without any network call, so benchmarks measure framework overhead only.
- Sample tools used by the tooled benchmarks.
- run_benchmarks(): runs a list of PerformanceEvals sequentially, prints
  summaries, and writes one JSON result file per benchmark when
  AGNO_BENCH_RESULTS_DIR is set.

Environment variables:

- AGNO_BENCH_RESULTS_DIR: directory to write JSON results into (optional).
- AGNO_BENCH_ITERATIONS: override the iteration count of every benchmark,
  e.g. for a quick smoke run (optional).
- AGNO_BENCH_QUIET: suppress the per-run tables and spinner (optional).
"""

import asyncio
import json
import os
import platform
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Iterator, List, Optional

from agno.eval.performance import PerformanceEval, PerformanceResult
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.base import RunStatus


# ---------------------------------------------------------------------------
# Mock Models (no network)
# ---------------------------------------------------------------------------
class MockModel(Model):
    """Minimal offline model: returns a canned text response without any network call.

    invoke_stream yields the response as a single chunk, so streaming
    benchmarks measure the fixed cost of the streaming machinery, not the
    per-chunk cost of a long delta stream.
    """

    def __init__(self, response_content: str = "ok"):
        super().__init__(id="mock-model", name="mock-model", provider="mock")
        self._mock_response = ModelResponse(
            content=response_content,
            role="assistant",
            response_usage=MessageMetrics(),
        )

    def get_instructions_for_model(self, *args, **kwargs):
        return None

    def get_system_message_for_model(self, *args, **kwargs):
        return None

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._mock_response

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._mock_response

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._mock_response

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._mock_response
        return

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


class MockToolModel(MockModel):
    """Offline model that requests one tool call, then answers once the tool result is present.

    This drives the full two-turn tool loop: model turn -> tool execution ->
    model turn -> final answer. The decision is stateless (based on whether a
    tool result message is already in the conversation) so every run behaves
    identically.
    """

    # Attribute names must not shadow Model internals: the base class defines
    # _tool_name as a method and uses it as a sort key inside _format_tools.
    def __init__(
        self,
        requested_tool: str = "add_numbers",
        requested_args: str = '{"a": 1, "b": 2}',
    ):
        super().__init__(response_content="done")
        self._requested_tool = requested_tool
        self._requested_args = requested_args

    def _make_response(self, messages) -> ModelResponse:
        has_tool_result = any(
            getattr(m, "role", None) == "tool" for m in (messages or [])
        )
        if has_tool_result:
            return ModelResponse(
                content="done", role="assistant", response_usage=MessageMetrics()
            )
        return ModelResponse(
            role="assistant",
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": self._requested_tool,
                        "arguments": self._requested_args,
                    },
                }
            ],
            response_usage=MessageMetrics(),
        )

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._make_response(kwargs.get("messages"))

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._make_response(kwargs.get("messages"))

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._make_response(kwargs.get("messages"))

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._make_response(kwargs.get("messages"))
        return


# ---------------------------------------------------------------------------
# Run Verification
# ---------------------------------------------------------------------------
def ensure_completed(
    run_output,
    expected_content: Optional[str] = None,
    expect_tool_success: bool = False,
):
    """Raise if a benchmarked run did not actually succeed.

    Agent.run() swallows errors into the run output instead of raising, so a
    broken benchmark would otherwise silently measure the error path. With
    expect_tool_success, also require at least one tool execution and no tool
    errors: the final model turn can answer normally even when the tool call
    itself failed. The checks cost nanoseconds against runs measured in
    hundreds of microseconds.
    """
    if run_output.status != RunStatus.completed:
        raise RuntimeError(
            "Benchmark run failed: status="
            + str(run_output.status)
            + " content="
            + str(run_output.content)
        )
    if expected_content is not None and run_output.content != expected_content:
        raise RuntimeError(
            "Benchmark run returned unexpected content: " + str(run_output.content)
        )
    if expect_tool_success:
        tools = run_output.tools or []
        if not tools:
            raise RuntimeError("Benchmark run executed no tools")
        for execution in tools:
            if execution.tool_call_error:
                raise RuntimeError(
                    "Benchmark tool call failed: " + str(execution.result)
                )
    return run_output


# ---------------------------------------------------------------------------
# Sample Tools
# ---------------------------------------------------------------------------
def add_numbers(a: int, b: int) -> int:
    """Add two numbers and return the result."""
    return a + b


def multiply_numbers(a: int, b: int) -> int:
    """Multiply two numbers and return the result."""
    return a * b


def get_weather(city: str) -> str:
    """Return the weather for a city."""
    return "sunny in " + city


def get_time(city: str) -> str:
    """Return the current time for a city."""
    return "12:00 in " + city


def get_news(topic: str) -> str:
    """Return the latest news for a topic."""
    return "no news about " + topic


# ---------------------------------------------------------------------------
# Machine Info
# ---------------------------------------------------------------------------
def get_machine_info() -> dict:
    """Best-effort description of the machine and build the benchmarks ran on."""
    info = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "python_version": platform.python_version(),
        "agno_version": _agno_version(),
        "git_commit": _git_commit(),
        "measured_at": datetime.now(timezone.utc).isoformat(),
    }
    chip = _mac_chip_name()
    if chip:
        info["processor"] = chip
    return info


def _agno_version() -> Optional[str]:
    try:
        from importlib.metadata import version

        return version("agno")
    except Exception:
        return None


def _git_commit() -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def _mac_chip_name() -> Optional[str]:
    if platform.system() != "Darwin":
        return None
    try:
        out = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Suite Summary Table
# ---------------------------------------------------------------------------
def print_summary_table(
    benchmarks: dict, machine: Optional[dict] = None, title: str = "Benchmark Summary"
) -> None:
    """Print one rich table over a suite's collected benchmark payloads.

    Time benchmarks show median and p95 (ms for import groups, us otherwise)
    plus their median allocation peak; memory-only benchmarks show KiB.
    """
    from rich.console import Console
    from rich.table import Table

    table = Table(title=title, show_header=True, header_style="bold magenta")
    table.add_column("Benchmark", style="cyan")
    table.add_column("Median", style="green", justify="right")
    table.add_column("p95", style="green", justify="right")
    table.add_column("Memory", style="yellow", justify="right")

    for name in sorted(benchmarks):
        payload = benchmarks[name]
        result = payload.get("result") or {}
        group = payload.get("group", "")
        mem_median = result.get("median_memory_usage") or 0.0
        mem_text = format(mem_median * 1024, ",.1f") + " KiB" if mem_median else "-"
        if result.get("run_times"):
            unit, scale = ("ms", 1e3) if "import" in group else ("us", 1e6)
            table.add_row(
                name,
                format(result["median_run_time"] * scale, ",.1f") + " " + unit,
                format(result["p95_run_time"] * scale, ",.1f") + " " + unit,
                mem_text,
            )
        else:
            table.add_row(name, "-", "-", mem_text)

    console = Console()
    if machine:
        parts = [
            "agno " + str(machine.get("agno_version") or "unknown"),
            "commit " + str(machine.get("git_commit") or "unknown"),
            str(machine.get("processor") or machine.get("machine") or ""),
        ]
        console.print(" | ".join(part for part in parts if part), style="dim")
    console.print(table)


# ---------------------------------------------------------------------------
# Benchmark Runner
# ---------------------------------------------------------------------------
def iterations(default: int) -> int:
    """Iteration count for a benchmark, honoring the AGNO_BENCH_ITERATIONS override."""
    override = os.getenv("AGNO_BENCH_ITERATIONS")
    if override:
        return max(1, int(override))
    return default


def quiet_mode() -> bool:
    return os.getenv("AGNO_BENCH_QUIET", "").lower() in ("1", "true", "yes")


def save_result(
    name: str,
    group: str,
    result: PerformanceResult,
    num_iterations: int,
    warmup_runs: int,
    extra: Optional[dict] = None,
) -> None:
    """Write one benchmark result as JSON into AGNO_BENCH_RESULTS_DIR, if set."""
    results_dir = os.getenv("AGNO_BENCH_RESULTS_DIR")
    if not results_dir:
        return
    payload = {
        "name": name,
        "group": group,
        "num_iterations": num_iterations,
        "warmup_runs": warmup_runs,
        "agno_version": _agno_version(),
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "result": asdict(result),
    }
    if extra:
        payload["extra"] = extra
    out_dir = Path(results_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / (name + ".json")
    out_path.write_text(json.dumps(payload, indent=2))
    print("Saved result: " + str(out_path))


def run_benchmarks(
    benchmarks: List[PerformanceEval], group: str
) -> List[PerformanceResult]:
    """Run PerformanceEvals sequentially and persist their results.

    Sync functions run via PerformanceEval.run(), async functions via
    PerformanceEval.arun(). Benchmarks must run one at a time: concurrent
    benchmarks contend for CPU and contaminate each other's timings.
    """
    quiet = quiet_mode()
    results: List[PerformanceResult] = []
    for bench in benchmarks:
        if quiet:
            bench.show_spinner = False
        print("")
        print("=== " + (bench.name or bench.func.__name__) + " ===")
        if asyncio.iscoroutinefunction(bench.func):
            result = asyncio.run(
                bench.arun(print_summary=not quiet, print_results=False)
            )
        else:
            result = bench.run(print_summary=not quiet, print_results=False)
        if quiet:
            print(
                "median "
                + format(result.median_run_time * 1e6, ".1f")
                + " us | p95 "
                + format(result.p95_run_time * 1e6, ".1f")
                + " us | mem median "
                + format(result.median_memory_usage * 1024, ".1f")
                + " KiB"
            )
        save_result(
            name=(bench.name or bench.func.__name__),
            group=group,
            result=result,
            num_iterations=bench.num_iterations,
            warmup_runs=bench.warmup_runs or 0,
        )
        results.append(result)
    return results
