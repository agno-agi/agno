"""Run `pip install agno openai` to install dependencies."""

import gc
import tracemalloc
import sys
from typing import Dict, Any, List
from dataclasses import fields
from agno.agent import Agent
from agno.eval.perf import PerfEval

def get_object_size(obj: Any) -> int:
    """Get the approximate size of an object in bytes."""
    return sys.getsizeof(obj)

def analyze_attribute_memory(obj: Any, attribute_name: str) -> Dict[str, Any]:
    """Analyze memory usage of a specific attribute."""
    value = getattr(obj, attribute_name)
    size = get_object_size(value)
    return {
        "name": attribute_name,
        "size_bytes": size,
        "size_mib": size / (1024 * 1024),
        "type": type(value).__name__
    }

def analyze_agent_memory(agent: Agent) -> List[Dict[str, Any]]:
    """Analyze memory usage of all Agent attributes."""
    memory_stats = []
    
    # Analyze each field
    for field in fields(agent):
        try:
            stats = analyze_attribute_memory(agent, field.name)
            memory_stats.append(stats)
        except Exception as e:
            memory_stats.append({
                "name": field.name,
                "error": str(e)
            })
    
    # Sort by size
    memory_stats.sort(key=lambda x: x.get("size_bytes", 0), reverse=True)
    return memory_stats

def instantiate_agent():
    return Agent(system_message='Be concise, reply with one sentence.')

instantiation_perf = PerfEval(func=instantiate_agent, num_iterations=1000)

def analyze_memory_usage(func):
    # Clear memory before measurement
    gc.collect()
    
    # Start tracing memory
    tracemalloc.start()
    
    # Run the function
    agent = func()
    
    # Get peak memory usage
    current, peak = tracemalloc.get_traced_memory()
    
    # Get top memory allocations
    snapshot = tracemalloc.take_snapshot()
    top_stats = snapshot.statistics('lineno')
    
    # Analyze Agent memory breakdown
    agent_memory_stats = analyze_agent_memory(agent)
    
    # Stop tracing memory
    tracemalloc.stop()
    
    # Print results
    print(f"\nOverall Memory Usage:")
    print(f"Current memory usage: {current / 1024 / 1024:.6f} MiB")
    print(f"Peak memory usage: {peak / 1024 / 1024:.6f} MiB")
    
    print("\nTop 10 Memory Allocations by Line:")
    for stat in top_stats[:10]:
        print(stat)
    
    print("\nAgent Memory Breakdown (Top 20 Largest Attributes):")
    for stat in agent_memory_stats[:20]:
        if "error" in stat:
            print(f"{stat['name']}: Error - {stat['error']}")
        else:
            print(f"{stat['name']}: {stat['size_mib']:.6f} MiB ({stat['type']})")

if __name__ == "__main__":
    # analyze_memory_usage(instantiate_agent)
    instantiation_perf.run(print_results=True)
    # print(instantiate_agent())
    
    