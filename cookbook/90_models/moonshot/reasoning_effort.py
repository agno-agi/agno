"""
Moonshot Reasoning Effort
=========================

Kimi K3 always reasons before answering. How much it thinks is controlled by the
top-level `reasoning_effort` parameter, which defaults to "max" when omitted.

"max" is a strong default - K3 can spend a minute or more thinking before answering a
prompt that does not need it. Dropping to "low" is several times faster, at the cost of
shallower reasoning. Use "max" for genuinely hard problems and "low" for everything
where latency matters more than depth.

The reasoning is returned as reasoning_content, which `show_full_reasoning=True`
renders alongside the answer.
"""

from agno.agent import Agent
from agno.models.moonshot import MoonShot

# ---------------------------------------------------------------------------
# Deep reasoning - the default, worth it for a hard problem
# ---------------------------------------------------------------------------

deep_agent = Agent(
    model=MoonShot(id="kimi-k3", reasoning_effort="max"),
    markdown=True,
)

task = (
    "A farmer needs to cross a river with a fox, a chicken and a sack of grain. "
    "The boat only fits the farmer and one item. The fox cannot be left alone with "
    "the chicken, and the chicken cannot be left alone with the grain. "
    "Provide a step-by-step solution."
)

# ---------------------------------------------------------------------------
# Low reasoning - much faster, for prompts that do not need deep thought
# ---------------------------------------------------------------------------

fast_agent = Agent(
    model=MoonShot(id="kimi-k3", reasoning_effort="low"),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agents
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    deep_agent.print_response(task, stream=True, show_full_reasoning=True)

    fast_agent.print_response("Share a 2 sentence horror story.", stream=True)
