# Cookbook Python Style Guide

This guide standardizes runnable cookbook `.py` examples.

## Core Pattern

1. Module docstring at the top:
- What this example demonstrates

2. Sectioned flow using banner comments:
- Setup section
- Instructions section
- `Create ...` section

3. Main execution gate:
- `if __name__ == "__main__":`
- Keep runnable demo steps in this block

4. No emoji characters in cookbook Python files.

## Recommended Skeleton

```python
"""
<Title>
=============================

<What this demonstrates>
"""

# ============================================================================
# Setup
# ============================================================================

# ============================================================================
# Agent Instructions
# ============================================================================
instructions = """..."""

# ============================================================================
# Create Agent
# ============================================================================
example_agent = Agent(...)

# ============================================================================
# Run Agent
# ============================================================================
if __name__ == "__main__":
    example_agent.print_response("...", stream=True)
```

## Validation

Run structure checks:

```bash
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/00_quickstart
```
