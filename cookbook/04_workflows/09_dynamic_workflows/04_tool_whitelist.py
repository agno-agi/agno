"""Dynamic Workflow - Tool whitelist and per-spawn selection.

Spawned agents only get tools from `allowed_tools`. The LLM picks a subset per spawn via
the `tools` parameter — anything not on the whitelist is silently filtered out. This is
the same security rail as PR #7387's dynamic subagents.

Demonstrates:
- `allowed_tools`: full set of tools the driver may delegate
- `allow_tool_selection=True` (default): LLM picks per-spawn from the whitelist
- Function-level filtering: even if you pass a Toolkit, only the named Function members the
  LLM requests are forwarded; whole-toolkit access is never auto-granted

Run:
    .venvs/demo/bin/python cookbook/04_workflows/09_dynamic_workflows/04_tool_whitelist.py
"""

from agno.models.openai import OpenAIResponses
from agno.tools.arxiv import ArxivTools
from agno.tools.calculator import CalculatorTools
from agno.tools.hackernews import HackerNewsTools
from agno.workflow import DynamicWorkflowDriver, Workflow


def main() -> None:
    driver = DynamicWorkflowDriver(
        model=OpenAIResponses(id="gpt-5.4"),
        instructions=(
            "Brief the user on their topic. Spawn specialists with focused tool access: "
            "an HN-aware researcher (use only HN tools), an academic researcher (use only "
            "Arxiv tools), and a final synthesizer (no tools)."
        ),
        allowed_tools=[
            HackerNewsTools(),
            ArxivTools(),
            CalculatorTools(),  # available but probably not needed
        ],
        allow_tool_selection=True,
        max_steps=5,
    )

    workflow = Workflow(
        name="DynamicMixedSourceBriefing",
        steps=driver,
    )

    result = workflow.run(
        input="Recent developments in retrieval-augmented generation (RAG)."
    )

    print("\n=== Final Briefing ===")
    print(result.content)
    print("\n=== Dynamic Plan (note the tools each spawn was given) ===")
    result.pretty_print_plan()

    for s in result.executed_steps:
        print(f"  spawn[{s.iteration}] role={s.role!r} tools={s.tools!r}")


if __name__ == "__main__":
    main()
