"""
Verified Tool: a tool call that carries a prediction
====================================================
The `step` tool advances a counter with one hidden rule: any amount above 5 is capped to 5.
The tool declares an optional `expect` parameter; the model fills it with its prediction of
the new counter value, and `verified_tool` compares the prediction with reality after the
call. A wrong prediction prefixes the result with a divergence block, so the model cannot
gloss over a plan that stopped matching the world.

verified_tool verifies one call. It cannot stop other calls the model batches into the same
message, so the instructions ask for exactly one step call per message: the model reads each
result before it spends the next step, and a divergence forces a replan before the plan is
finished.
"""

from typing import Optional

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.verify import verified_tool

state = {"n": 0, "calls": []}


def same_value(result: str, expect: str) -> bool:
    return result.strip() == expect.strip()


@verified_tool(same_value)
def step(amount: int, expect: Optional[str] = None) -> str:
    """Advance the counter by `amount` and return the new value.

    Args:
        amount: How much to add.
        expect: Your prediction of the new counter value, as a string. Send an empty string
            when you have no prediction.
    """
    state["n"] += min(amount, 5)
    state["calls"].append((amount, expect, state["n"]))
    return str(state["n"])


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[step],
    instructions=[
        "You drive a counter that starts at 0 with the step tool. Your goal is a counter of exactly 17.",
        "Use as few step calls as you can: plan the amounts up front, then execute the plan.",
        "Issue exactly one step call per message. Read its result before deciding the next call.",
        "Always fill expect with the value you predict the counter will show after the call.",
        "If a result diverges from your prediction, say what the tool actually does and replan from the real value.",
        "Keep going until the counter shows 17, then reply with the final value and what you learned about the tool.",
    ],
)

response = agent.run("Take the counter from 0 to exactly 17.")

print("tool calls (amount, expect, new value):")
for call in state["calls"]:
    print("  ", call)
print()
print("final counter:", state["n"])
print()
print(response.content)
