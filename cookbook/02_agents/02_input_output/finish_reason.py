"""
Finish Reason
=============================

Read why the model stopped generating from RunOutput.finish_reason.

The normalized FinishReason is consistent across providers (stop, length, tool_call,
content_filter, pause, refusal, error, unknown). The raw provider value is preserved under
model_provider_data["native_finish_reason"].

A truncated answer (the model hit the output token cap) reports FinishReason.LENGTH instead of
looking exactly like a clean completion.
"""

from agno.agent import Agent, RunOutput
from agno.models.finish_reason import FinishReason
from agno.models.openai import OpenAIResponses

# A normal completion stops on its own -> FinishReason.STOP
agent = Agent(model=OpenAIResponses(id="gpt-5.5"))

# A tiny output cap forces truncation -> FinishReason.LENGTH (a warning is logged)
truncating_agent = Agent(model=OpenAIResponses(id="gpt-5.5", max_output_tokens=16))

if __name__ == "__main__":
    run_output: RunOutput = agent.run(
        "Give me one short sentence about the printing press."
    )
    print("Normal run")
    print("  content:", run_output.content)
    print("  finish_reason:", run_output.finish_reason)

    truncated: RunOutput = truncating_agent.run(
        "Write a 500-word essay on the history of the printing press."
    )
    print("Truncated run")
    print("  content:", truncated.content)
    print("  finish_reason:", truncated.finish_reason)
    print("  is truncated:", truncated.finish_reason == FinishReason.LENGTH)
    if truncated.model_provider_data:
        print(
            "  native_finish_reason:",
            truncated.model_provider_data.get("native_finish_reason"),
        )
