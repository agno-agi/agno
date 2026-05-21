"""Dynamic Workflow - Claude-Code-style code review.

Demonstrates a real "agentic coding" flow on top of a dynamic-mode WorkflowAgent. The driver
LLM is given two tools its spawned specialists can use:

- `Workspace`: read_file / edit_file / write_file / list_files / search_content over
  a project root (sandboxed; the agent can only touch files under `root`).
- `ExaTools`: web search for cross-referencing patterns, looking up best practices,
  finding similar code in the wild.

The user asks the driver to audit a specific Python class for gaps, leave in-file
comments where issues are found, and produce a `.md` report with concrete next steps.
The driver decomposes this into specialist spawns — code reader, analyst, fixer,
report writer — and runs them in sequence, each one picking from the allowed tools.

Requires:
- `EXA_API_KEY` in your environment
- The target file exists at the path below (defaults to agno's own `agent.py`)

Run:
    .venvs/demo/bin/python cookbook/04_workflows/09_dynamic_workflows/07_code_review.py
"""

from pathlib import Path

from agno.models.openai import OpenAIResponses
from agno.tools.exa import ExaTools
from agno.tools.workspace import Workspace
from agno.workflow import Workflow, WorkflowAgent

# The project root the workspace tool is scoped to. The agent can't touch anything
# above this — passing `root=` to Workspace is the sandboxing rail.
PROJECT_ROOT = Path(__file__).resolve().parents[3]  # cookbook/.. = agno repo root

# Relative path inside PROJECT_ROOT that the driver will audit.
TARGET_FILE = "libs/agno/agno/agent/agent.py"
TARGET_CLASS = "Agent"

# Where the driver writes its findings. Relative to PROJECT_ROOT.
REPORT_PATH = "tmp/agent_class_audit.md"


def main() -> None:
    workspace = Workspace(
        root=str(PROJECT_ROOT),
        allowed=["read", "edit", "write", "list", "search"],
    )

    agent = WorkflowAgent(
        model=OpenAIResponses(id="gpt-5.4"),
        instructions=(
            "You are an agentic code-review orchestrator. The user wants you to audit a "
            "specific Python class for major design or correctness gaps, leave in-file "
            "comments where issues are found, and produce a Markdown report with "
            "concrete next steps.\n\n"
            "Pattern to follow:\n"
            "  1. Spawn a 'code_reader' specialist with the `read_file` and `search_content` "
            "tools. Have it locate the target class and produce a concise structural map "
            "(methods, key fields, notable patterns) plus the relevant line ranges.\n"
            "  2. Spawn a 'gap_analyst' with the `search_content` tool (and optionally web "
            "search via exa_*). Have it cross-reference the code with how similar classes "
            "elsewhere in the repo or in published patterns are structured, and identify "
            "3-5 concrete gaps with line-number references.\n"
            "  3. Spawn a 'comment_writer' with the `read_file` and `edit_file` tools. "
            "Have it add concise `# AUDIT:` comments at the precise lines where gaps "
            "were found — one comment per gap, no rewrites of surrounding code.\n"
            "  4. Spawn a 'report_writer' with the `write_file` tool. Have it produce a "
            "Markdown report at the path the user specifies, listing each gap, the file "
            "and line, why it matters, and a concrete fix recommendation.\n"
            "After step 4, return a short final response summarizing what you did and "
            "pointing the user at the report."
        ),
        allowed_tools=[workspace, ExaTools()],
        max_steps=6,
        step_summary_max_chars=2000,  # specialist outputs are long; let the driver see more
    )

    workflow = Workflow(
        name="DynamicCodeReview",
        description="Driver invents code-reader / analyst / commenter / report-writer specialists.",
        agent=agent,
    )

    user_request = (
        f"Go through `{TARGET_FILE}` and audit the `{TARGET_CLASS}` class for major design "
        f"or correctness gaps. Leave in-file `# AUDIT:` comments at the exact lines where you "
        f"find issues. Then write a Markdown report at `{REPORT_PATH}` with one section per "
        f"gap: the file and line, why it matters, and concrete next steps to fix it."
    )

    print(f"Workflow root: {PROJECT_ROOT}")
    print(f"Target file:   {TARGET_FILE}")
    print(f"Target class:  {TARGET_CLASS}")
    print(f"Report:        {REPORT_PATH}\n")

    workflow.print_response(input=user_request, stream=True, stream_events=True)

    report_full_path = PROJECT_ROOT / REPORT_PATH
    print(f"\nReport at: {report_full_path}")
    if report_full_path.exists():
        print("(first 40 lines of report:)\n")
        for line in report_full_path.read_text().splitlines()[:40]:
            print(f"  | {line}")


if __name__ == "__main__":
    main()
