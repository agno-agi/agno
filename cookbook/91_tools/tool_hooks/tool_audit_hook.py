"""
Tool Audit Hook
=============================

Demonstrates the ToolAuditHook for logging all tool calls made by an agent.
Useful for compliance, debugging, and observability.

The audit hook records:
- Tool name and arguments
- Result (truncated) or error
- Duration in milliseconds
- Timestamp (UTC)

Output is written as JSONL (one JSON object per line) for easy parsing.

Sample JSONL output::

    {"timestamp": "2026-05-03T22:45:00+00:00", "tool_name": "duckduckgo_search",
     "status": "success", "arguments": {"query": "AI news"}, "duration_ms": 342.15,
     "result": "{\"results\": [...]}"}
    {"timestamp": "2026-05-03T22:45:01+00:00", "tool_name": "duckduckgo_news",
     "status": "error", "arguments": {"query": "weather"}, "duration_ms": 1205.33,
     "error": "Connection timeout"}
"""

from agno.agent import Agent
from agno.hooks import ToolAuditHook
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

# ---------------------------------------------------------------------------
# Example 1: Log to file
# ---------------------------------------------------------------------------

agent_file_audit = Agent(
    name="Audited Search Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    tool_hooks=[ToolAuditHook(log_file="tool_audit.jsonl")],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Example 2: Log to callback
# ---------------------------------------------------------------------------

audit_records = []


def collect_audit(record):
    """Callback that collects audit records in memory."""
    audit_records.append(record)
    print(f"  [AUDIT] {record['tool_name']} -> {record['status']} ({record.get('duration_ms', 0):.0f}ms)")


agent_callback_audit = Agent(
    name="Callback Audited Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    tool_hooks=[ToolAuditHook(callback=collect_audit)],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Example 3: Filtered audit (only log specific tools)
# ---------------------------------------------------------------------------

agent_filtered_audit = Agent(
    name="Filtered Audit Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    tool_hooks=[
        ToolAuditHook(
            log_file="filtered_audit.jsonl",
            include_tools=["duckduckgo_search"],
            log_results=False,  # Don't log results, only tool name + args + duration
        )
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Example 4: Both file and callback
# ---------------------------------------------------------------------------

agent_dual_audit = Agent(
    name="Dual Audit Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    tool_hooks=[
        ToolAuditHook(
            log_file="full_audit.jsonl",
            callback=collect_audit,
            max_result_length=500,
        )
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Example 5: Compliance mode — block tool execution if audit fails
# ---------------------------------------------------------------------------

agent_compliance = Agent(
    name="Compliance Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    tool_hooks=[
        ToolAuditHook(
            log_file="/secure/audit/tool_calls.jsonl",
            fail_on_log_error=True,  # No audit = no tool execution
        )
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Example 6: Exclude noisy tools from audit
# ---------------------------------------------------------------------------

agent_exclude = Agent(
    name="Selective Audit Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    tool_hooks=[
        ToolAuditHook(
            callback=collect_audit,
            exclude_tools=["duckduckgo_news"],  # Skip noisy news tool
            log_arguments=False,  # Hide potentially sensitive query args
        )
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Example 1: File audit ===")
    agent_file_audit.print_response("What is the latest news about AI?", stream=True)
    print("\nAudit log written to tool_audit.jsonl")

    print("\n=== Example 2: Callback audit ===")
    agent_callback_audit.print_response("What is the weather in San Francisco?", stream=True)
    print(f"\nCollected {len(audit_records)} audit records in memory")

    print("\n=== Example 3: Filtered audit ===")
    agent_filtered_audit.print_response("Search for Python tutorials", stream=True)
