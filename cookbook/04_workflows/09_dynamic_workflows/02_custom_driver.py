"""Dynamic Workflow - Python custom driver.

Same dynamic-mode `WorkflowAgent` as the basic example, but the orchestration logic is plain
Python instead of an LLM. The driver still creates ephemeral specialist agents on demand
(role, instructions, tools picked at spawn time) — the difference is who picks them.

Use this when you want:
- deterministic control over which agents run, in what order
- to avoid LLM variability in orchestration
- to demonstrate or test specific plans

Run:
    .venvs/demo/bin/python cookbook/04_workflows/09_dynamic_workflows/02_custom_driver.py
"""

from agno.models.openai import OpenAIResponses
from agno.workflow import Workflow, WorkflowAgent


def my_python_driver(workflow_input: str, spawn) -> str:
    """research -> (maybe) fact_check -> summarize."""
    research = spawn(
        role="researcher",
        instructions=(
            "Produce a concise list of 3-5 verifiable claims about the user's topic, "
            "one per line. Prefix any controversial claim with '[CONTROVERSIAL] '."
        ),
        input=workflow_input,
    )

    if "CONTROVERSIAL" in research.upper():
        fact_check = spawn(
            role="fact_checker",
            instructions=(
                "For each claim, state whether it is well-supported, contested, or unclear, "
                "with a one-sentence rationale."
            ),
            input=research,
        )
        context = f"Original research:\n{research}\n\nFact-check pass:\n{fact_check}"
    else:
        context = research

    return spawn(
        role="summarizer",
        instructions="Write a tight, well-structured briefing of 3-4 short paragraphs.",
        input=context,
    )


def main() -> None:
    agent = WorkflowAgent(
        model=OpenAIResponses(id="gpt-5.4"),
        custom_driver=my_python_driver,
        max_steps=5,
    )

    workflow = Workflow(
        name="DynamicResearchBriefing-PythonDriven",
        description="Python driver decides which specialist agents to spawn, in what order.",
        agent=agent,
    )

    workflow.print_response(
        input="The health effects of microplastics in drinking water.",
        stream=True,
        stream_events=True,
    )


if __name__ == "__main__":
    main()
