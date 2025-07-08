"""
Example demonstrating how to use enhanced memory tracking to identify memory growth.

This script shows how to:
1. Enable debug mode to see detailed memory allocations
2. Track memory growth between runs
3. Identify specific code locations causing memory leaks
"""

import os
import time
from typing import List

from agno.eval.performance import PerformanceEval


def memory_leaking_function():
    """A function that intentionally leaks memory for demonstration."""
    # This list will grow with each call
    if not hasattr(memory_leaking_function, "data"):
        memory_leaking_function.data = []

    # Add more data each time
    memory_leaking_function.data.extend([i for i in range(10000)])

    # Simulate some work
    time.sleep(0.01)


def normal_function():
    """A function that doesn't leak memory."""
    # Create temporary data that gets cleaned up
    temp_data = [i for i in range(10000)]

    # Simulate some work
    time.sleep(0.01)

    # Data goes out of scope and gets cleaned up


async def async_memory_leaking_function():
    """An async function that intentionally leaks memory."""
    # This list will grow with each call
    if not hasattr(async_memory_leaking_function, "data"):
        async_memory_leaking_function.data = []

    # Add more data each time
    async_memory_leaking_function.data.extend([i for i in range(10000)])

    # Simulate some async work
    await asyncio.sleep(0.01)


def main():
    """Demonstrate memory tracking with debug output."""

    # Enable debug mode to see detailed memory information
    os.environ["AGNO_DEBUG"] = "true"

    print("=== Memory Leaking Function Analysis ===")

    # Create performance evaluator with debug mode enabled
    eval_leaking = PerformanceEval(
        func=memory_leaking_function,
        name="Memory Leaking Function",
        num_iterations=5,  # Fewer iterations for clearer output
        warmup_runs=2,
        debug_mode=True,
        print_summary=True,
        print_results=True,
    )

    # Run the evaluation with growth tracking to see what's growing between runs
    result = eval_leaking.run_with_growth_tracking()

    print(f"\n=== Normal Function Analysis ===")

    # Create performance evaluator for normal function
    eval_normal = PerformanceEval(
        func=normal_function,
        name="Normal Function",
        num_iterations=5,
        warmup_runs=2,
        debug_mode=True,
        print_summary=True,
        print_results=True,
    )

    # Run the evaluation with growth tracking
    result = eval_normal.run_with_growth_tracking()

    print(f"\n=== Key Observations ===")
    print("1. The memory leaking function shows increasing memory usage across runs")
    print("2. The normal function shows consistent memory usage")
    print("3. Growth tracking shows exactly what's being added between runs")
    print("4. Look for the 'Memory growth analysis' section in debug output")
    print("5. Focus on lines that show positive growth (+X MiB)")


async def async_main():
    """Demonstrate async memory tracking."""

    # Enable debug mode
    os.environ["AGNO_DEBUG"] = "true"

    print("=== Async Memory Leaking Function Analysis ===")

    # Create async performance evaluator
    eval_async = PerformanceEval(
        func=async_memory_leaking_function,
        name="Async Memory Leaking Function",
        num_iterations=5,
        warmup_runs=2,
        debug_mode=True,
        print_summary=True,
        print_results=True,
    )

    # Run the async evaluation
    result = await eval_async.arun()


if __name__ == "__main__":
    import asyncio

    # Run sync example
    main()

    # Run async example
    asyncio.run(async_main())
