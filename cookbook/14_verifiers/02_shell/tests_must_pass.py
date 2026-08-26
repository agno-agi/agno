"""
Tests Must Pass
===============
ShellVerifier makes a command's exit code the definition of done. Here the agent must fix
a broken function until the test suite actually passes; "I fixed it" counts for nothing.

The verifier runs `pytest -q` in the scratch project after every attempt. Exit 0 passes;
anything else sends the test output back to the model as evidence.
"""

import tempfile
from pathlib import Path
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.file import FileTools
from agno.verifiers import ShellVerifier

# ---------------------------------------------------------------------------
# A scratch project with a failing test
# ---------------------------------------------------------------------------

project = Path(tempfile.mkdtemp(prefix="tests_must_pass_"))
(project / "calc.py").write_text(
    dedent(
        """
        def add(a, b):
            return a - b
        """
    ).strip()
    + "\n"
)
(project / "test_calc.py").write_text(
    dedent(
        """
        from calc import add


        def test_add():
            assert add(2, 3) == 5
        """
    ).strip()
    + "\n"
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[FileTools(base_dir=project)],
    verifiers=[ShellVerifier("python -m pytest -q", cwd=str(project), timeout_s=60.0)],
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

output = agent.run("The test in this project fails. Read the code and fix the bug in calc.py.")

print("status:", output.status)
print("verification:", output.verification.status, "/", output.verification.stop_reason)
for attempt in output.verification.attempts:
    for verdict in attempt.verdicts:
        first_line = verdict.report.splitlines()[0] if verdict.report else ""
        print("attempt", attempt.index, "->", "PASS" if verdict.passed else "FAIL", first_line)
