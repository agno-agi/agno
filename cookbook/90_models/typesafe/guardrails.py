"""Jev input checks and an output grounding check with explicit evidence."""

from agno.agent import Agent
from agno.guardrails.typesafe import JevGuardrail
from agno.models.openai import OpenAIResponses


def grounding_state(run_output, run_context):
    return {
        "output": run_output.content,
        "evidence": run_context.dependencies["evidence"],
    }


agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    dependencies={
        "evidence": "The standard plan allows 3 seats. The premium plan allows 20 seats."
    },
    add_dependencies_to_context=True,
    instructions="Answer using only the supplied evidence.",
    pre_hooks=[JevGuardrail.prompt_injection(threshold=0.85)],
    post_hooks=[JevGuardrail.grounding(threshold=0.8, state_builder=grounding_state)],
)

if __name__ == "__main__":
    # Output checks need the whole response. stream=True is rejected before generation.
    response = agent.run("How many seats does the premium plan allow?", stream=False)
    print(response.status)
    print(response.content)
