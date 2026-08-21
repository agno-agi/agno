"""Live-model tests for agno.verify. Each test keeps its task tiny: a continuation is a paid
model run, and the always-fail case deliberately burns the whole budget."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.file import FileTools
from agno.verify import VERIFICATION_NOTICE, ShellVerifier, VerifierLimits, run_verified

pytestmark = pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="needs OPENAI_API_KEY")

MODEL_ID = "gpt-5.5"


def _agent(workdir: Path, db=None, **kwargs) -> Agent:
    return Agent(
        model=OpenAIResponses(id=MODEL_ID),
        tools=[FileTools(base_dir=workdir)],
        instructions=[
            "You work inside a scratch directory through the file tools. Do the task, then stop.",
            VERIFICATION_NOTICE,
        ],
        db=db,
        markdown=False,
        **kwargs,
    )


def test_file_must_exist_gate_passes_within_limits():
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        target = workdir / "hello.txt"

        def file_exists(run):
            return target.exists() or f"{target.name} does not exist in the working directory yet"

        result = run_verified(
            _agent(workdir),
            "Create a file named hello.txt containing the single word hello.",
            verifiers=[file_exists],
            limits=VerifierLimits(max_continuations=2),
        )
        assert result.status == "verified", [a.verdicts for a in result.attempts]
        assert target.read_text().strip().lower().startswith("hello")


def test_always_failing_verifier_burns_budget_and_leaves_pending_rows():
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        db = SqliteDb(db_file=str(workdir / "verify.db"))
        agent = _agent(workdir, db=db, add_history_to_context=False)

        def never(run):
            return "the host check rejects every answer in this test"

        limits = VerifierLimits(max_continuations=1)
        result = run_verified(
            agent, "Reply with the word ready.", verifiers=[never], limits=limits, session_id="live-22"
        )

        assert result.status == "unverified"
        assert result.stop_reason == "exhausted"
        assert len(result.attempts) == 1 + limits.max_continuations

        session = agent.get_session(session_id="live-22")
        runs = session.runs or []
        assert len(runs) == 1 + limits.max_continuations
        by_id = {r.run_id: r for r in runs}
        for attempt in result.attempts[1:]:
            row = by_id[attempt.run_id]
            user_messages = [m for m in (row.messages or []) if m.role == "user"]
            assert '<verification attempt="' in (user_messages[-1].content or "")
            snapshot = (row.metadata or {}).get("verification")
            assert snapshot is not None and snapshot["status"] == "pending"
            assert len(snapshot["attempts"]) == attempt.index
        # The final verdict lives on the returned object, not on any row.
        assert result.output.metadata["verification"]["status"] == "unverified"


def test_shell_verifier_gates_a_real_pytest_fix():
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        (workdir / "calc.py").write_text("def add(a, b):\n    return a - b\n")
        (workdir / "test_calc.py").write_text("from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n")
        # Prove the scratch test really fails before the agent touches it.
        before = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "test_calc.py"], cwd=workdir, capture_output=True
        )
        assert before.returncode != 0

        result = run_verified(
            _agent(workdir),
            "test_calc.py fails. Read calc.py and test_calc.py, fix the bug in calc.py, and stop. Do not edit the test.",
            verifiers=[ShellVerifier(f"{sys.executable} -m pytest -q test_calc.py", cwd=str(workdir), name="pytest")],
            limits=VerifierLimits(max_continuations=2),
        )
        assert result.status == "verified", [a.verdicts for a in result.attempts]
        assert "return a + b" in (workdir / "calc.py").read_text().replace(" ", " ")
