"""Benchmark _wire_google_auth performance."""

import sys
import time


# Measure cold import cost
def benchmark_cold_import():
    """Measure cost of importing Google modules."""
    # Clear from cache to measure cold import
    modules_to_clear = [k for k in sys.modules if "agno.tools.google" in k]
    for m in modules_to_clear:
        del sys.modules[m]

    start = time.perf_counter_ns()

    end = time.perf_counter_ns()

    return (end - start) / 1_000_000  # ms


def benchmark_cached_import(iterations: int = 10000):
    """Measure cost of cached imports."""
    # Ensure already imported

    start = time.perf_counter_ns()
    for _ in range(iterations):
        pass
    end = time.perf_counter_ns()

    return (end - start) / iterations  # ns per iteration


def benchmark_wire_google_auth():
    """Benchmark _wire_google_auth in various scenarios."""
    from agno.agent._tools import _wire_google_auth
    from agno.tools import Toolkit
    from agno.tools.google.calendar import GoogleCalendarTools
    from agno.tools.google.gmail import GmailTools
    from agno.tools.google.oauth_tools import GoogleOAuthTools

    iterations = 10000
    results = {}

    # Scenario 1: None
    start = time.perf_counter_ns()
    for _ in range(iterations):
        _wire_google_auth(None)
    end = time.perf_counter_ns()
    results["None"] = (end - start) / iterations

    # Scenario 2: Empty list
    tools = []
    start = time.perf_counter_ns()
    for _ in range(iterations):
        _wire_google_auth(tools)
    end = time.perf_counter_ns()
    results["empty_list"] = (end - start) / iterations

    # Scenario 3: Non-Google toolkit
    class DummyToolkit(Toolkit):
        def __init__(self):
            super().__init__(name="dummy")

    tools = [DummyToolkit() for _ in range(5)]
    start = time.perf_counter_ns()
    for _ in range(iterations):
        _wire_google_auth(tools)
    end = time.perf_counter_ns()
    results["5_non_google_tools"] = (end - start) / iterations

    # Scenario 4: 1 Google toolkit (first run - needs wiring)
    gmail = GmailTools()
    gmail.oauth_config = None  # Reset
    tools = [gmail]
    _wire_google_auth(tools)  # Wire once

    # Now benchmark subsequent runs (already wired)
    start = time.perf_counter_ns()
    for _ in range(iterations):
        _wire_google_auth(tools)
    end = time.perf_counter_ns()
    results["1_gmail_already_wired"] = (end - start) / iterations

    # Scenario 5: Multiple Google toolkits (already wired)
    gmail = GmailTools()
    calendar = GoogleCalendarTools()
    oauth = GoogleOAuthTools()
    tools = [gmail, calendar, oauth]
    _wire_google_auth(tools)  # Wire once

    start = time.perf_counter_ns()
    for _ in range(iterations):
        _wire_google_auth(tools)
    end = time.perf_counter_ns()
    results["gmail+calendar+oauth_wired"] = (end - start) / iterations

    # Scenario 6: Mixed tools
    tools = [DummyToolkit() for _ in range(10)] + [GmailTools(), GoogleCalendarTools()]
    _wire_google_auth(tools)  # Wire once

    start = time.perf_counter_ns()
    for _ in range(iterations):
        _wire_google_auth(tools)
    end = time.perf_counter_ns()
    results["10_dummy_2_google_wired"] = (end - start) / iterations

    # Scenario 7: First-time wiring cost
    wiring_times = []
    for _ in range(100):
        gmail = GmailTools()
        gmail.oauth_config = None
        calendar = GoogleCalendarTools()
        calendar.oauth_config = None
        tools = [gmail, calendar]

        start = time.perf_counter_ns()
        _wire_google_auth(tools)
        end = time.perf_counter_ns()
        wiring_times.append(end - start)

    results["first_wire_2_google"] = sum(wiring_times) / len(wiring_times)

    return results


def benchmark_full_get_tools():
    """Benchmark the full get_tools() call to see _wire_google_auth's share."""
    from agno.agent import Agent
    from agno.models.openai import OpenAIResponses
    from agno.run import RunContext
    from agno.run.agent import RunOutput
    from agno.session import AgentSession
    from agno.tools.google.gmail import GmailTools

    # Agent with Google tools
    agent = Agent(
        model=OpenAIResponses(id="gpt-4o"),
        tools=[GmailTools()],
    )

    run_context = RunContext(agent_id=agent.id)
    run_response = RunOutput(
        run_id="test",
        agent_id=agent.id,
        session_id="test",
    )
    session = AgentSession(session_id="test")

    # Warm up
    from agno.agent._tools import get_tools

    get_tools(agent, run_response, run_context, session)

    iterations = 1000
    start = time.perf_counter_ns()
    for _ in range(iterations):
        get_tools(agent, run_response, run_context, session)
    end = time.perf_counter_ns()

    return (end - start) / iterations  # ns per call


def benchmark_memory():
    """Benchmark memory impact of _wire_google_auth."""
    import gc
    import tracemalloc

    results = {}

    # Clean slate
    gc.collect()

    # 1. Memory for importing Google modules (already imported, measure objects)
    tracemalloc.start()
    from agno.tools.google.auth import GoogleOAuthConfig
    from agno.tools.google.calendar import GoogleCalendarTools
    from agno.tools.google.gmail import GmailTools
    from agno.tools.google.oauth_tools import GoogleOAuthTools

    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    results["google_imports_current"] = current
    results["google_imports_peak"] = peak

    # 2. Memory for a single GoogleOAuthConfig
    gc.collect()
    tracemalloc.start()
    _config = GoogleOAuthConfig()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    results["single_oauth_config"] = current

    # 3. Memory for GoogleOAuthConfig with registered services
    gc.collect()
    tracemalloc.start()
    config2 = GoogleOAuthConfig()
    config2.register_service("gmail", ["https://www.googleapis.com/auth/gmail.modify"])
    config2.register_service("calendar", ["https://www.googleapis.com/auth/calendar"])
    config2.register_service("drive", ["https://www.googleapis.com/auth/drive"])
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    results["oauth_config_3_services"] = current

    # 4. Memory for a single GmailTools instance
    gc.collect()
    tracemalloc.start()
    gmail = GmailTools()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    results["single_gmail_tools"] = current

    # 5. Memory for wiring 3 Google toolkits
    gc.collect()
    tracemalloc.start()
    from agno.agent._tools import _wire_google_auth

    gmail = GmailTools()
    gmail.oauth_config = None
    calendar = GoogleCalendarTools()
    calendar.oauth_config = None
    oauth = GoogleOAuthTools()
    oauth.oauth_config = None
    tools = [gmail, calendar, oauth]
    _wire_google_auth(tools)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    results["3_toolkits_wired"] = current
    results["3_toolkits_wired_peak"] = peak

    # 6. Memory growth from repeated wiring (should be ~0 if idempotent)
    gc.collect()
    gmail = GmailTools()
    calendar = GoogleCalendarTools()
    tools = [gmail, calendar]
    _wire_google_auth(tools)  # Initial wire

    tracemalloc.start()
    for _ in range(1000):
        _wire_google_auth(tools)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    results["1000_repeated_wires"] = current

    # 7. Memory for 100 separate agents with Google tools (simulating multi-user)
    gc.collect()
    tracemalloc.start()
    agents_tools = []
    for _ in range(100):
        gmail = GmailTools()
        calendar = GoogleCalendarTools()
        tools = [gmail, calendar]
        _wire_google_auth(tools)
        agents_tools.append(tools)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    results["100_agents_2_google_each"] = current
    results["100_agents_per_agent"] = current / 100

    return results


def format_bytes(b):
    """Format bytes as human readable."""
    if b < 1024:
        return f"{b} B"
    elif b < 1024 * 1024:
        return f"{b / 1024:.1f} KB"
    else:
        return f"{b / (1024 * 1024):.2f} MB"


if __name__ == "__main__":
    print("=" * 60)
    print("_wire_google_auth Performance Benchmark")
    print("=" * 60)

    print("\n1. Cold import cost (first import of Google modules):")
    cold_ms = benchmark_cold_import()
    print(f"   {cold_ms:.2f} ms")

    print("\n2. Cached import cost (subsequent imports):")
    cached_ns = benchmark_cached_import()
    print(f"   {cached_ns:.1f} ns ({cached_ns / 1000:.3f} us)")

    print("\n3. _wire_google_auth scenarios (10k iterations each):")
    results = benchmark_wire_google_auth()
    for scenario, ns in results.items():
        print(f"   {scenario:35s}: {ns:8.1f} ns ({ns / 1000:.3f} us)")

    print("\n4. Full get_tools() call (1k iterations):")
    try:
        full_ns = benchmark_full_get_tools()
        print(f"   {full_ns:.1f} ns ({full_ns / 1000:.1f} us, {full_ns / 1_000_000:.3f} ms)")
    except Exception as e:
        print(f"   Skipped: {e}")

    print("\n" + "=" * 60)
    print("Memory Impact")
    print("=" * 60)
    mem_results = benchmark_memory()
    print("\n5. Memory allocation:")
    for scenario, bytes_used in mem_results.items():
        print(f"   {scenario:35s}: {format_bytes(bytes_used):>10s}")

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print("   Model API call:              ~100-500 ms")
    print(f"   _wire_google_auth (hot):     ~{results.get('gmail+calendar+oauth_wired', 0) / 1000:.1f} us")
    print(f"   Ratio:                       ~{100_000_000 / results.get('gmail+calendar+oauth_wired', 1):.0f}x faster")
    print(f"\n   Memory per agent (2 Google): {format_bytes(int(mem_results.get('100_agents_per_agent', 0)))}")
    print(f"   Memory for 1000 re-wires:    {format_bytes(mem_results.get('1000_repeated_wires', 0))}")
