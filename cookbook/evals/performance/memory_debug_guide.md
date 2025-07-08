# Memory Debugging Guide

This guide explains how to use the enhanced memory tracking features in Agno's performance evaluation to identify what's causing memory growth.

## Quick Start

To see what's causing memory growth in your function:

```python
import os
from agno.eval.performance import PerformanceEval

# Enable debug mode
os.environ["AGNO_DEBUG"] = "true"

# Create evaluator with debug mode
eval = PerformanceEval(
    func=your_function,
    debug_mode=True,
    num_iterations=5,  # Start with fewer iterations for clearer output
    print_summary=True
)

# Run with growth tracking
result = eval.run_with_growth_tracking()
```

## What You'll See

When debug mode is enabled, you'll see detailed output like:

```
[DEBUG] Raw peak usage: 45.234567 MiB, Adjusted: 12.345678 MiB
[DEBUG] Top 10 memory allocations:
  1500 blocks: 8.5 MiB
    File "/path/to/your/file.py", line 42
      data = [i for i in range(10000)]
  200 blocks: 2.1 MiB
    File "/path/to/your/file.py", line 45
      result = process_data(data)
[DEBUG] Memory usage by file:
  8.5 MiB: /path/to/your/file.py
  2.1 MiB: /path/to/other/file.py
[DEBUG] Memory growth analysis:
[DEBUG] Top 10 memory growth sources:
  +1.2 MiB: 500 new blocks
    File "/path/to/your/file.py", line 42
      data = [i for i in range(10000)]
[DEBUG] Total memory growth: 1.2 MiB
```

## Key Features

### 1. Detailed Allocation Information
- **Top allocations**: Shows the largest memory allocations with exact line numbers
- **File-based grouping**: Groups allocations by source file
- **Block counts**: Shows how many memory blocks were allocated

### 2. Memory Growth Tracking
- **Between-run comparison**: Compares memory snapshots between iterations
- **Growth sources**: Identifies exactly what's being added between runs
- **Total growth**: Shows cumulative memory growth

### 3. Debug Mode Options
- **Basic tracking**: Use `run()` with `debug_mode=True`
- **Growth tracking**: Use `run_with_growth_tracking()` for detailed growth analysis

## Common Memory Leak Patterns

### 1. Accumulating Data
```python
# BAD: Data accumulates across calls
def leaking_function():
    if not hasattr(leaking_function, 'data'):
        leaking_function.data = []
    leaking_function.data.extend([i for i in range(10000)])

# GOOD: Data is cleaned up
def clean_function():
    data = [i for i in range(10000)]
    # Data goes out of scope and gets cleaned up
```

### 2. Cached Objects
```python
# BAD: Cache grows indefinitely
def cached_function():
    if not hasattr(cached_function, 'cache'):
        cached_function.cache = {}
    cached_function.cache[time.time()] = large_object()

# GOOD: Limited cache size
def limited_cache_function():
    if not hasattr(limited_cache_function, 'cache'):
        limited_cache_function.cache = {}
    
    # Limit cache size
    if len(limited_cache_function.cache) > 100:
        # Remove oldest entries
        oldest_keys = sorted(limited_cache_function.cache.keys())[:10]
        for key in oldest_keys:
            del limited_cache_function.cache[key]
```

### 3. Event Listeners
```python
# BAD: Listeners accumulate
def add_listener():
    if not hasattr(add_listener, 'listeners'):
        add_listener.listeners = []
    add_listener.listeners.append(callback_function)

# GOOD: Remove listeners when done
def managed_listeners():
    if not hasattr(managed_listeners, 'listeners'):
        managed_listeners.listeners = []
    
    listener = callback_function
    managed_listeners.listeners.append(listener)
    
    # Clean up when appropriate
    def cleanup():
        managed_listeners.listeners.remove(listener)
    
    return cleanup
```

## Interpreting Debug Output

### Memory Growth Analysis
- **Positive growth**: Memory is being added between runs
- **Zero growth**: Memory usage is stable
- **Negative growth**: Memory is being freed (good!)

### Top Allocations
- **Large block counts**: Many small objects being created
- **Large individual blocks**: Few large objects
- **Repeated patterns**: Same line appearing multiple times indicates a loop or repeated operation

### File-based Analysis
- **Your code files**: Look for your own code causing allocations
- **Library files**: External libraries might be caching or accumulating data
- **System files**: Usually normal, but can indicate system-level issues

## Best Practices

### 1. Start Small
```python
# Begin with fewer iterations for clearer output
eval = PerformanceEval(
    func=your_function,
    num_iterations=3,  # Start small
    debug_mode=True
)
```

### 2. Isolate the Problem
```python
# Test individual components
def test_component_a():
    # Test just component A
    pass

def test_component_b():
    # Test just component B
    pass

# Run separate evaluations to isolate the leak
```

### 3. Use Growth Tracking
```python
# Always use growth tracking for memory leak detection
result = eval.run_with_growth_tracking()
```

### 4. Monitor Over Time
```python
# Run multiple evaluations to see patterns
for i in range(3):
    result = eval.run_with_growth_tracking()
    print(f"Evaluation {i+1} complete")
```

## Troubleshooting

### No Debug Output
- Ensure `AGNO_DEBUG=true` is set
- Check that `debug_mode=True` is passed to PerformanceEval
- Verify your logging level includes DEBUG messages

### Unclear Results
- Reduce `num_iterations` for clearer output
- Increase `warmup_runs` to stabilize baseline
- Run the function manually to understand its behavior

### System Memory vs Process Memory
- The measurements show process memory, not system memory
- Some memory might be shared between processes
- Garbage collection timing can affect measurements

## Advanced Usage

### Custom Memory Analysis
```python
def custom_memory_analysis():
    import tracemalloc
    
    tracemalloc.start()
    your_function()
    snapshot = tracemalloc.take_snapshot()
    tracemalloc.stop()
    
    # Custom analysis
    stats = snapshot.statistics('lineno')
    for stat in stats[:5]:
        print(f"{stat.size / 1024 / 1024:.1f} MiB: {stat.traceback.format()}")
```

### Memory Profiling with cProfile
```python
import cProfile
import pstats

def profile_memory_and_cpu():
    profiler = cProfile.Profile()
    profiler.enable()
    
    # Your function here
    your_function()
    
    profiler.disable()
    stats = pstats.Stats(profiler)
    stats.sort_stats('cumulative')
    stats.print_stats(10)
```

This enhanced memory tracking will help you identify exactly what's causing memory growth in your functions, making it much easier to fix memory leaks and optimize performance. 