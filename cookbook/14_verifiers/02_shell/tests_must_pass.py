"""
Tests Must Pass
===============
ShellVerifier makes a command's exit code the definition of done. Here the agent must fix
a broken function until the test suite actually passes.

The verifier runs `pytest -q` after every attempt. Exit 0 passes; anything else sends the
test output back to the model as evidence. The suite also covers a subtract function the
prompt never mentions, so attempt 0 fixes add and still fails, and attempt 1 adds subtract
from the pytest output.

The command runs under the shell on the host with no sandboxing, and its exit code is the
whole verdict. Anything the agent can write, the agent can use to green the check: a test
file, a conftest.py, a pytest.ini, a shim on sys.path in cwd. So the agent's tools are
scoped to src/ and the tests live in a sibling checks/ directory the agent cannot write,
with the command run from there against the sources the agent can edit.
"""

import sys
from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.file import FileTools
from agno.verifiers import ShellVerifier

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

# Writable sources in src/, read-only tests in checks/; both files are rewritten every run.
PROJECT = Path("tmp/verifiers/tests_must_pass")
SRC = PROJECT / "src"
CHECKS = PROJECT / "checks"
SRC.mkdir(parents=True, exist_ok=True)
CHECKS.mkdir(parents=True, exist_ok=True)

(SRC / "calc.py").write_text("def add(a, b):\n    return a - b\n")
(CHECKS / "test_calc.py").write_text(
    "import calc\n\n\n"
    "def test_add():\n"
    "    assert calc.add(2, 3) == 5\n\n\n"
    "def test_subtract():\n"
    "    assert calc.subtract(5, 3) == 2\n"
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[FileTools(base_dir=SRC)],
    verifiers=[
        ShellVerifier(
            f"{sys.executable} -m pytest -q",
            cwd=str(CHECKS),
            env={"PYTHONPATH": str(SRC.resolve())},
            timeout=60.0,
        )
    ],
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_output = agent.run("The add function in calc.py is broken. Fix the bug in add.")

    verification = run_output.verification
    print(f"Status: {run_output.status.value}")
    print(
        f"Verification: {verification.status.value} / {verification.stop_reason.value}"
    )
    for attempt in verification.attempts:
        for verdict in attempt.verdicts:
            result = "PASS" if verdict.passed else "FAIL"
            returncode = (verdict.detail or {}).get("returncode")
            # A passing verdict carries no report; a failing one ends with pytest's summary line.
            summary = verdict.report.splitlines()[-1] if verdict.report else ""
            print(f"Attempt {attempt.index}: {result} | exit {returncode} | {summary}")
