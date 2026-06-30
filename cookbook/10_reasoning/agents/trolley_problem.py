"""
Trolley Problem Analysis
========================

Demonstrates built-in and DeepSeek-backed reasoning for ethical analysis.
"""

from agno.agent import Agent
from agno.models.deepseek import DeepSeek
from agno.models.openai import OpenAIChat

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
cot_prompt = (
    "Solve the trolley problem. Evaluate multiple ethical frameworks. "
    "Include an ASCII diagram of your solution."
)

deepseek_prompt = (
    "You are a philosopher tasked with analyzing the classic 'Trolley Problem'. In this scenario, a runaway trolley "
    "is barreling down the tracks towards five people who are tied up and unable to move. You are standing next to "
    "a large stranger on a footbridge above the tracks. The only way to save the five people is to push this stranger "
    "off the bridge onto the tracks below. This will kill the stranger, but save the five people on the tracks. "
    "Should you push the stranger to save the five people? Provide a well-reasoned answer considering utilitarian, "
    "deontological, and virtue ethics frameworks. "
    "Include a simple ASCII art diagram to illustrate the scenario."
)

cot_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    reasoning=True,
    markdown=True,
)

deepseek_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    reasoning_model=DeepSeek(id="deepseek-reasoner"),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agents
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Built-in Chain Of Thought ===")
    cot_agent.print_response(cot_prompt, stream=True, show_full_reasoning=True)

    print("\n=== DeepSeek Reasoning Model ===")
    deepseek_agent.print_response(deepseek_prompt, stream=True)
