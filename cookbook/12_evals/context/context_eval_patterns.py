"""Patterns ContextEval deterministic evaluation method."""

from agno.eval.context import ContextEval

evaluation = ContextEval(
    name="Code Response Patterns",
    patterns=[
        r"```python",  # Must have code block
        r"\bdef\b",  # Must have function definition
    ],
    occurrence_patterns={
        r"#\s*.+": 2,  # At least 2 comments (# followed by text)
    },
    pattern_target="output",  # Check patterns in output only
    threshold=7,
)

# Sample output to evaluate
output = """
Here's a function to calculate factorial:

```python
def factorial(n):
    # Base case: factorial of 0 or 1 is 1
    if n <= 1:
        return 1
    # Recursive case: n * factorial(n-1)
    return n * factorial(n - 1)
```
"""

result = evaluation.run(
    input="Write a factorial function",
    output=output,
    print_results=True,
    print_summary=True,
)

print(f"Pattern Score: {result.avg_pattern_score:.2f}")
print(f"Passed: {result.results[0].passed}")
