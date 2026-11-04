"""
Dynamic Reasoning Toggle
========================

Enable or disable the configured reasoning model independently for each run.
Run with `python cookbook/10_reasoning/models/groq/dynamic_reasoning_toggle.py`.
Requires GROQ_API_KEY.
"""

from agno.agent import Agent
from agno.models.groq import Groq
from agno.run.agent import RunEvent

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=Groq(id="openai/gpt-oss-120b"),
    reasoning_model=Groq(id="openai/gpt-oss-120b"),
)

# ---------------------------------------------------------------------------
# Run Agent with and without reasoning
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    for prompt, reasoning in [
        ("Hi!", False),
        ("What is 23 x 47?", True),
    ]:
        print(f"\nReasoning enabled: {reasoning}")
        for event in agent.run(
            prompt, reasoning=reasoning, stream=True, stream_events=True
        ):
            if event.event in {
                RunEvent.reasoning_started,
                RunEvent.reasoning_completed,
                RunEvent.run_completed,
            }:
                print(event.event)
            elif event.event == RunEvent.run_content and event.content:
                print(event.content, end="", flush=True)
        print()
