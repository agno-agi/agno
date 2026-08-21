"""
Comparison Harness
==================

Shared setup for the cross-framework comparison benchmarks. Reuses the main
suite's harness (_bench.py) from the parent directory and provides safe
environment defaults: a placeholder OpenAI key (model clients are constructed
but never called) and telemetry opt-outs for frameworks that phone home.

Run these benchmarks with the dedicated comparison environment, which has
langgraph, crewai and pydantic-ai installed next to agno:

    uv venv .venvs/compare --python 3.12
    uv pip install --python .venvs/compare/bin/python -e libs/agno \
        langgraph langchain-openai crewai pydantic-ai
"""

import os
import sys
from pathlib import Path

# The comparison files reuse the parent suite's harness
sys.path.insert(0, str(Path(__file__).parent.parent))

# Placeholder credentials and telemetry opt-outs. Model clients are only
# constructed, never invoked, so the key value is irrelevant. run_all.py sets
# these before the subprocess starts; this is the fallback for standalone runs
# (crewai reads its telemetry setting at import, so import _compare first).
os.environ.setdefault("OPENAI_API_KEY", "placeholder-not-used")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("CREWAI_TELEMETRY_OPT_OUT", "true")
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("AGNO_TELEMETRY", "false")

from _bench import (  # noqa: E402,F401
    MockModel,
    ensure_completed,
    get_machine_info,
    iterations,
    run_benchmarks,
    save_result,
)
