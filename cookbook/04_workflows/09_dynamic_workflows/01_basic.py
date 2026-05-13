"""Dynamic Workflow - Basic (LLM-driven).

The simplest dynamic workflow: hand a `DynamicWorkflowDriver` to `Workflow(steps=...)`. The
driver is an LLM agent with one tool, `spawn_agent`, which invents a fresh specialist agent
(role, instructions, tools) on each call and runs it. The driver keeps spawning until it has
enough information, then produces the final response.

Demonstrates:
- minimal LLM-driven setup (just `model` + `instructions`)
- `allowed_tools` so spawned agents can do real work
- `max_steps` cap
- `executed_steps` trail + `pretty_print_plan()` on the result

Run:
    .venvs/demo/bin/python cookbook/04_workflows/09_dynamic_workflows/01_basic.py
"""

from agno.models.openai import OpenAIResponses
from agno.tools.hackernews import HackerNewsTools
from agno.workflow import DynamicWorkflowDriver, Workflow


def main() -> None:
    driver = DynamicWorkflowDriver(
        model=OpenAIResponses(id="gpt-5.4"),
        instructions=(
            "Produce a briefing on what HackerNews is currently saying about the user's topic. "
            "Spawn specialists in sequence: a researcher to pull relevant top stories, "
            "optionally an analyst to extract themes, and a summarizer to write the final briefing."
        ),
        allowed_tools=[HackerNewsTools()],
        max_steps=4,
    )

    workflow = Workflow(
        name="DynamicHackerNewsBriefing",
        description="The driver invents its own specialist agents per run.",
        steps=driver,
    )

    result = workflow.run(
        input="What is HackerNews currently discussing about AI agent frameworks?"
    )

    print("\n=== Final Briefing ===")
    print(result.content)
    print("\n=== Dynamic Plan (what the driver actually ran) ===")
    result.pretty_print_plan()


if __name__ == "__main__":
    main()
