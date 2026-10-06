"""An eval must not discard allocations belonging to an already-active tracer."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("growth", [False, True])
def test_public_memory_eval_preserves_existing_tracer(tmp_path, mode, growth):
    script = tmp_path / "tracer.py"
    script.write_text(
        """
import asyncio
import sys
import tracemalloc

from agno.eval.performance import PerformanceEval


def sync_work():
    return bytearray(128)


async def async_work():
    return bytearray(128)


tracemalloc.start(7)
payload = bytearray(512 * 1024)
peak = tracemalloc.get_traced_memory()[1]
assert tracemalloc.get_object_traceback(payload) is not None
try:
    evaluation = PerformanceEval(
        func=sync_work if sys.argv[1] == "sync" else async_work,
        warmup_runs=0,
        num_iterations=1,
        measure_runtime=False,
        memory_growth_tracking=sys.argv[2] == "True",
        show_spinner=False,
        telemetry=False,
    )
    refused = False
    try:
        if sys.argv[1] == "sync":
            evaluation.run()
        else:
            asyncio.run(evaluation.arun())
    except RuntimeError as exc:
        assert "tracemalloc is already tracing" in str(exc)
        refused = True
    assert tracemalloc.is_tracing()
    assert tracemalloc.get_traceback_limit() == 7
    assert tracemalloc.get_traced_memory()[1] >= peak
    assert tracemalloc.get_object_traceback(payload) is not None
    assert refused, "Memory evaluation must refuse an already-active tracer"
    print("existing tracing session preserved")
finally:
    tracemalloc.stop()
""",
        encoding="utf-8",
    )
    source = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [sys.executable, str(script), mode, str(growth)],
        capture_output=True,
        text=True,
        timeout=10,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join([str(source), os.environ.get("PYTHONPATH", "")]),
            "AGNO_TELEMETRY": "false",
        },
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "existing tracing session preserved"
