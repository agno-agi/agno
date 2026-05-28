"""Dynamic Workflow - Cost-aware model tiers.

The driver itself runs on one model, but each spawned specialist can use a different model
chosen at spawn time. The LLM picks tier *labels* (e.g. "fast", "powerful") — never raw
model strings — so there's no hallucination risk and you can swap the underlying model in
one place.

Demonstrates:
- `model_tiers`: label -> model id mapping
- `allow_model_tier_selection=True`: exposes a `model_tier` parameter to the LLM
- `tier_hints`: shown to the LLM alongside tier names so it picks well

Run:
    .venvs/demo/bin/python cookbook/04_workflows/09_dynamic_workflows/03_model_tiers.py
"""

from agno.models.openai import OpenAIResponses
from agno.tools.hackernews import HackerNewsTools
from agno.workflow import DynamicWorkflowDriver, Workflow


def main() -> None:
    driver = DynamicWorkflowDriver(
        model=OpenAIResponses(id="gpt-5.4"),
        instructions=(
            "Produce a briefing on the user's topic from HackerNews. "
            "Use `model_tier='fast'` for simple extraction or formatting tasks, "
            "and `model_tier='powerful'` for synthesis or analysis. "
            "Spawn 2-4 specialists, then write the final briefing."
        ),
        allowed_tools=[HackerNewsTools()],
        model_tiers={
            "fast": "openai:gpt-5.4",
            "powerful": "openai:gpt-5.4",
        },
        allow_model_tier_selection=True,
        tier_hints={
            "fast": "extraction, formatting, simple classification",
            "powerful": "complex reasoning, multi-source synthesis",
        },
        max_steps=4,
    )

    workflow = Workflow(
        name="DynamicTieredBriefing",
        steps=driver,
    )

    workflow.print_response(
        input="What is HackerNews saying about LLM evals?",
        stream=True,
        stream_events=True,
    )
    # Spawn panels above include the model tier picked per spawn (when set).
    # Inspect result.executed_steps[i].model_tier in code for programmatic access.


if __name__ == "__main__":
    main()
