"""
Deepseek Reasoning Effort
=========================

DeepSeek V4 models accept a `reasoning_effort` parameter that controls how much the
model thinks before answering. Valid values are "high" and "max" ("low" and "medium"
are mapped to "high" server-side). It is left unset by default, so the API uses its
own default ("high"). For demanding agent scenarios, DeepSeek recommends "max".

Note: while thinking mode is active, temperature, top_p, presence_penalty and
frequency_penalty are ignored by the API.
"""

from agno.agent import Agent
from agno.models.deepseek import DeepSeek

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=DeepSeek(id="deepseek-v4-pro", reasoning_effort="max"),
    markdown=True,
)

task = (
    "A farmer needs to cross a river with a fox, a chicken and a sack of grain. "
    "The boat only fits the farmer and one item. The fox cannot be left alone with "
    "the chicken, and the chicken cannot be left alone with the grain. "
    "Provide a step-by-step solution."
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(task, stream=True, show_full_reasoning=True)
