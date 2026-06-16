"""
Dynamic Subagents — Model Tier Selection
==========================================

Demonstrates cost-aware model routing per spawned subagent.
The developer defines tiers (fast / standard / powerful) backed by real
model IDs. The LLM picks a label at spawn time, never a raw model string,
so there is no hallucination risk and models can be rotated without
touching LLM behavior.

Cost impact:
An orchestrator on the standard tier spawning a "fast" subagent for simple
extraction uses the mini variant for that subtask (~20-30x cheaper per
token). At production scale this compounds significantly.

Prompts to try:
- "Extract the numbers from 'Revenue was $4.2M, up 18%'. Then explain transformer attention in 3 paragraphs."
- "Classify this text as positive/negative: 'I love this product'. Then write a detailed product review."
"""

import asyncio

from agno.agent import Agent, SubAgentConfig
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Subagent Template
# ---------------------------------------------------------------------------
subagent_template = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="cost_aware_orchestrator",
    model=OpenAIResponses(id="gpt-5.4"),
    enable_dynamic_subagents=True,
    subagent_template=subagent_template,
    subagent_config=SubAgentConfig(
        model_tiers={
            "fast": "gpt-5.4-mini",
            "standard": "gpt-5.4",
            "powerful": "o3",
        },
        allow_model_tier_selection=True,
        max_concurrent=3,
    ),
    instructions=(
        "You are a cost-aware orchestrator. When delegating tasks via "
        "spawn_agent, select the cheapest model tier that can do the job:\n"
        "  - 'fast'     for simple extraction, formatting, yes/no classification\n"
        "  - 'standard' for summarisation, code generation, analysis\n"
        "  - 'powerful' for complex multi-step reasoning or research synthesis\n"
        "Default to 'standard' when unsure."
    ),
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
async def main() -> None:
    await agent.aprint_response(
        "Do three things:\n"
        "1. Extract just the numbers from this text: "
        "'Revenue was $4.2M, up 18% YoY, with 342 new customers'\n"
        "2. Write a 3-paragraph explanation of transformer attention mechanisms\n"
        "3. Analyse the trade-offs between microservices and monolith architecture "
        "for a 10-person startup",
        stream=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
