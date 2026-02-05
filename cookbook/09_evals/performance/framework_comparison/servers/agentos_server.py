"""
Minimal AgentOS Server for Performance Benchmarking

Usage:
    python cookbook/09_evals/performance/framework_comparison/servers/agentos_server.py

Server runs at http://localhost:7778
"""

import os

os.environ["AGNO_TELEMETRY"] = "false"

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.utils.log import set_log_level_to_error

set_log_level_to_error()

benchmark_agent = Agent(
    id="benchmark-agent",
    name="Benchmark Agent",
    model=OpenAIChat(id="gpt-4o"),
    system_message="You are a helpful assistant. Be concise.",
    telemetry=False,
    add_history_to_context=False,
    enable_session_summaries=False,
)

agent_os = AgentOS(
    description="Performance benchmark server",
    agents=[benchmark_agent],
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="agentos_server:app", port=7778, reload=False)
