"""
Confident AI Observability Integration
======================================

Demonstrates sending Agno agent traces to Confident AI with confident-trace.

confident-trace is an OpenTelemetry-native tracing SDK that detects Agno
automatically. Call init() once at startup and your agent, tool, and model
calls show up in the Confident AI Observatory with no other changes.

Setup:
    pip install agno openai confident-trace

Set CONFIDENT_API_KEY and OPENAI_API_KEY before running this example.
For the EU region, also set CONFIDENT_OTEL_ENDPOINT to
https://eu.otel.confident-ai.com/v1/traces.
See https://www.confident-ai.com/docs/llm-tracing/introduction for details.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.hackernews import HackerNewsTools
from confident_trace import init, shutdown, trace_context

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
# Initialize once at startup. This reads CONFIDENT_API_KEY from the
# environment and instruments Agno and the OpenAI SDK.
init()


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Hacker News Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[HackerNewsTools()],
    instructions="You summarize Hacker News stories. Be concise and cite story titles.",
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        # A plain run is traced automatically.
        agent.print_response("What are the top 3 stories on Hacker News right now?")

        # Attach tags, metadata, and a user ID to the trace before the run starts.
        with trace_context(
            tags=["cookbook"],
            metadata={"release": "2026-09"},
            user_id="user-42",
        ):
            agent.print_response(
                "Pick one of those stories and explain why it is trending.",
                stream=True,
            )
    finally:
        # Flush pending spans before the process exits.
        shutdown()
