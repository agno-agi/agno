"""
Tests Must Pass: a shell command as the definition of done
==========================================================
ShellVerifier runs a command; exit code 0 is the only pass. The agent is asked to fix a bug
in a scratch module whose test fails; pytest decides when it is actually fixed, and its
output is the evidence the model reads when it is not.

A scratch directory is created so nothing touches your checkout.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.file import FileTools
from agno.verify import VERIFICATION_NOTICE, ShellVerifier, VerifierLimits, run_verified

workdir = Path(tempfile.mkdtemp(prefix="tests_must_pass_"))
(workdir / "calc.py").write_text("def add(a, b):\n    return a - b\n")
(workdir / "test_calc.py").write_text(
    "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
)

before = subprocess.run(
    [sys.executable, "-m", "pytest", "-q", "test_calc.py"],
    cwd=workdir,
    capture_output=True,
)
print("pytest before the agent runs: exit", before.returncode)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[FileTools(base_dir=workdir)],
    instructions=[
        "You work inside a scratch directory through the file tools.",
        VERIFICATION_NOTICE,
    ],
)

pytest_gate = ShellVerifier(
    f"{sys.executable} -m pytest -q test_calc.py",
    cwd=str(workdir),
    timeout_s=60,
    name="pytest",
)

result = run_verified(
    agent,
    "test_calc.py fails. Read calc.py and test_calc.py, fix the bug in calc.py, and stop. Do not edit the test.",
    verifiers=[pytest_gate],
    limits=VerifierLimits(max_continuations=2),
)

print("status:", result.status)
for attempt in result.attempts:
    for verdict in attempt.verdicts:
        print(
            f"attempt {attempt.index} [{'PASS' if verdict.passed else 'FAIL'}] {verdict.name}"
        )
        if not verdict.passed:
            print("  " + verdict.report.splitlines()[0])
print("calc.py now:")
print((workdir / "calc.py").read_text())
