"""
Metrics Display Utility - Universal metrics logging for all Agno agents

This utility provides comprehensive metrics tracking and display for agent runs,
demonstrating the METRICS feature of Agno framework.

Features:
- Run-level metrics (tokens, cost, latency, tools used)
- Session-level metrics (aggregate statistics)
- Clean terminal formatting
- Universal compatibility with all agents
- Logging support for AgentOS/uvicorn environments

Usage:
    from utils.metrics_display import display_run_metrics, display_session_metrics

    # After agent run
    run_response = agent.run("your query")
    display_run_metrics(run_response)
    display_session_metrics(agent)
"""

import logging
from typing import Any, Optional

from agno.agent import Agent

# Configure logger for metrics display
logger = logging.getLogger("agno.metrics")
logger.setLevel(logging.INFO)


def format_cost(cost: Optional[float]) -> str:
    """Format cost in dollars with appropriate precision"""
    if cost is None:
        return "N/A"
    if cost < 0.01:
        return f"${cost:.4f}"
    return f"${cost:.2f}"


def format_duration(seconds: Optional[float]) -> str:
    """Format duration in human-readable format"""
    if seconds is None:
        return "N/A"
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    return f"{seconds:.2f}s"


def display_run_metrics(run_response: Any, show_message_metrics: bool = False) -> None:
    """
    Display metrics for a single agent run in terminal.

    Shows:
    - Total tokens (prompt + completion)
    - Cost breakdown
    - Response latency
    - Tools called

    Args:
        run_response: The RunResponse object from agent.run() or agent.print_response()
        show_message_metrics: If True, show per-message metrics breakdown
    """
    if not run_response:
        print("\n⚠️  No run response available")
        return

    print("\n" + "─" * 70)
    print("📊 RUN METRICS")
    print("─" * 70)

    if run_response.metrics:
        metrics = run_response.metrics

        # Token usage
        prompt_tokens = getattr(metrics, 'input_tokens', None) or getattr(metrics, 'prompt_tokens', None)
        completion_tokens = getattr(metrics, 'output_tokens', None) or getattr(metrics, 'completion_tokens', None)
        total_tokens = getattr(metrics, 'total_tokens', None)

        if prompt_tokens or completion_tokens or total_tokens:
            print("\n🔢 Token Usage:")
            if prompt_tokens:
                print(f"   Prompt Tokens:     {prompt_tokens:,}")
            if completion_tokens:
                print(f"   Completion Tokens: {completion_tokens:,}")
            if total_tokens:
                print(f"   Total Tokens:      {total_tokens:,}")

        # Cost breakdown
        prompt_cost = getattr(metrics, 'input_cost', None) or getattr(metrics, 'prompt_cost', None)
        completion_cost = getattr(metrics, 'output_cost', None) or getattr(metrics, 'completion_cost', None)
        total_cost = getattr(metrics, 'total_cost', None)

        if prompt_cost or completion_cost or total_cost:
            print("\n💰 Cost Breakdown:")
            if prompt_cost:
                print(f"   Prompt Cost:       {format_cost(prompt_cost)}")
            if completion_cost:
                print(f"   Completion Cost:   {format_cost(completion_cost)}")
            if total_cost:
                print(f"   Total Cost:        {format_cost(total_cost)}")

        # Timing information
        time_to_first_token = getattr(metrics, 'time_to_first_token', None)
        response_timer = getattr(metrics, 'response_timer', None)

        if time_to_first_token or response_timer:
            print("\n⏱️  Timing:")
            if time_to_first_token:
                print(f"   Time to First Token: {format_duration(time_to_first_token)}")
            if response_timer:
                print(f"   Total Response Time: {format_duration(response_timer)}")

        # Tools used
        if hasattr(run_response, 'messages') and run_response.messages:
            tools_called = []
            for message in run_response.messages:
                if hasattr(message, 'tool_calls') and message.tool_calls:
                    for tool_call in message.tool_calls:
                        if hasattr(tool_call, 'function') and hasattr(tool_call.function, 'name'):
                            tools_called.append(tool_call.function.name)

            if tools_called:
                print("\n🔧 Tools Called:")
                for i, tool in enumerate(tools_called, 1):
                    print(f"   {i}. {tool}")
    else:
        print("\n⚠️  No metrics available for this run")

    # Message-level metrics (optional detailed breakdown)
    if show_message_metrics and hasattr(run_response, 'messages') and run_response.messages:
        print("\n" + "─" * 70)
        print("📨 MESSAGE-LEVEL METRICS")
        print("─" * 70)

        for i, message in enumerate(run_response.messages, 1):
            if message.role == "assistant" and message.metrics:
                print(f"\n   Message {i}:")
                msg_metrics = message.metrics

                # Token info
                msg_tokens = getattr(msg_metrics, 'total_tokens', None)
                if msg_tokens:
                    print(f"      Tokens: {msg_tokens:,}")

                # Cost info
                msg_cost = getattr(msg_metrics, 'total_cost', None)
                if msg_cost:
                    print(f"      Cost: {format_cost(msg_cost)}")

    print("\n" + "─" * 70)


def display_session_metrics(agent: Agent) -> None:
    """
    Display aggregate session metrics for an agent.

    Shows:
    - Total runs in session
    - Total tokens consumed
    - Total cost
    - Average latency

    Args:
        agent: The Agent instance to get session metrics from
    """
    print("\n" + "═" * 70)
    print("📈 SESSION METRICS")
    print("═" * 70)

    try:
        session_metrics = agent.get_session_metrics()

        if session_metrics:
            # Run count
            total_runs = getattr(session_metrics, 'total_runs', None)
            if total_runs:
                print(f"\n🔄 Total Runs: {total_runs}")

            # Token usage
            total_input_tokens = getattr(session_metrics, 'total_input_tokens', None)
            total_output_tokens = getattr(session_metrics, 'total_output_tokens', None)
            total_tokens = getattr(session_metrics, 'total_tokens', None)

            if total_input_tokens or total_output_tokens or total_tokens:
                print("\n🔢 Token Usage:")
                if total_input_tokens:
                    print(f"   Total Prompt Tokens:     {total_input_tokens:,}")
                if total_output_tokens:
                    print(f"   Total Completion Tokens: {total_output_tokens:,}")
                if total_tokens:
                    print(f"   Total Tokens:            {total_tokens:,}")

            # Cost
            total_cost = getattr(session_metrics, 'total_cost', None)
            if total_cost:
                print(f"\n💰 Total Cost: {format_cost(total_cost)}")

            # Timing
            avg_time = getattr(session_metrics, 'avg_response_time', None)
            total_time = getattr(session_metrics, 'total_response_time', None)

            if avg_time or total_time:
                print("\n⏱️  Timing:")
                if total_time:
                    print(f"   Total Response Time: {format_duration(total_time)}")
                if avg_time:
                    print(f"   Avg Response Time:   {format_duration(avg_time)}")
        else:
            print("\n⚠️  No session metrics available yet")
            print("   (Metrics are collected after running the agent)")

    except Exception as e:
        print(f"\n⚠️  Error retrieving session metrics: {e}")

    print("\n" + "═" * 70)


def display_all_metrics(run_response: Any, agent: Agent, show_message_metrics: bool = False) -> None:
    """
    Convenience function to display both run and session metrics.

    Args:
        run_response: The RunResponse object from agent.run()
        agent: The Agent instance
        show_message_metrics: If True, show per-message metrics breakdown
    """
    display_run_metrics(run_response, show_message_metrics)
    display_session_metrics(agent)


def display_metrics_post_hook(run_output: Any, agent: Agent) -> None:
    """
    Post-hook function that automatically logs metrics after agent execution.

    This hook is designed to be used with Agno's post_hooks parameter on Agent instances.
    It will log compact metrics using Python's logging module, which uvicorn/AgentOS
    will display in the server console.

    Args:
        run_output: The RunOutput object from the agent execution
        agent: The Agent instance

    Usage:
        from utils.metrics_display import display_metrics_post_hook

        agent = Agent(
            # ... other config
            post_hooks=[display_metrics_post_hook]
        )
    """
    # Check if run_output has metrics
    if not hasattr(run_output, "metrics") or not run_output.metrics:
        return

    metrics = run_output.metrics

    # Extract key metrics
    total_tokens = getattr(metrics, "total_tokens", None)
    total_cost = getattr(metrics, "total_cost", None)
    response_timer = getattr(metrics, "response_timer", None)

    # Count tools called
    tools_called = []
    if hasattr(run_output, "messages") and run_output.messages:
        for message in run_output.messages:
            if hasattr(message, "tool_calls") and message.tool_calls:
                for tool_call in message.tool_calls:
                    if hasattr(tool_call, "function") and hasattr(tool_call.function, "name"):
                        tools_called.append(tool_call.function.name)

    # Build metrics summary
    metrics_parts = []

    if total_tokens:
        metrics_parts.append(f"Tokens: {total_tokens:,}")

    if total_cost:
        metrics_parts.append(f"Cost: {format_cost(total_cost)}")

    if response_timer:
        metrics_parts.append(f"Time: {format_duration(response_timer)}")

    if tools_called:
        tools_str = ", ".join(tools_called[:3])
        if len(tools_called) > 3:
            tools_str += f" (+{len(tools_called) - 3} more)"
        metrics_parts.append(f"Tools: {tools_str}")

    # Log metrics
    if metrics_parts:
        metrics_summary = " | ".join(metrics_parts)
        logger.info(f"📊 RUN METRICS: {metrics_summary}")

        # Also print for direct console visibility
        print(f"\n📊 RUN METRICS: {metrics_summary}\n")
