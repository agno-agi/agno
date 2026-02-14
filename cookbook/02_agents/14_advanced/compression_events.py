"""
Compression Events
=============================

Test script to verify compression events are working correctly.
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.run.agent import RunEvent
from agno.tools.duckduckgo import DuckDuckGoTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[DuckDuckGoTools()],
    description="Specialized in tracking competitor activities",
    instructions="Use the search tools and always use the latest information and data.",
    compress_tool_results=True,
)


async def main():
    print("--- Running agent with compression events ---")

    stream = agent.arun(
        """
        Research recent activities for these AI companies:
        1. OpenAI - latest news
        2. Anthropic - latest news
        3. Google DeepMind - latest news
        """,
        stream=True,
        stream_events=True,
    )

    async for chunk in stream:
        if chunk.event == RunEvent.run_started.value:
            print(f"[RunStarted] model={chunk.model}")

        elif chunk.event == RunEvent.model_request_started.value:
            print(f"[ModelRequestStarted] model={chunk.model}")

        elif chunk.event == RunEvent.model_request_completed.value:
            print(
                f"[ModelRequestCompleted] tokens: in={chunk.input_tokens}, out={chunk.output_tokens}"
            )

        elif chunk.event == RunEvent.tool_call_started.value:
            print(f"[ToolCallStarted] {chunk.tool.tool_name}")

        elif chunk.event == RunEvent.tool_call_completed.value:
            print(f"[ToolCallCompleted] {chunk.tool.tool_name}")

        elif chunk.event == RunEvent.compression_started.value:
            print("[CompressionStarted]")

        elif chunk.event == RunEvent.compression_completed.value:
            print(
                f"[CompressionCompleted] compressed={chunk.tool_results_compressed} results"
            )
            print(
                f"  Original: {chunk.original_size} chars -> Compressed: {chunk.compressed_size} chars"
            )
            if chunk.original_size and chunk.compressed_size:
                ratio = (1 - chunk.compressed_size / chunk.original_size) * 100
                print(f"  Compression ratio: {ratio:.1f}% reduction")

        elif chunk.event == RunEvent.run_completed.value:
            print("[RunCompleted]")


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    asyncio.run(main())
