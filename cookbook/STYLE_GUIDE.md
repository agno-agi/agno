# Cookbook Python Style Guide

This guide standardizes runnable cookbook `.py` examples.

## Core Pattern

1. Module docstring at the top:
- What this example demonstrates
- Key concepts
- Prompts or inputs to try

2. Sectioned flow using banner comments:
- Config sections (storage, tools, knowledge, schemas) as needed
- Instructions section
- `Create ...` section
- `Run ...` section
- Optional `More Examples` section

3. Main execution gate:
- `if __name__ == "__main__":`
- Keep runnable demo steps in this block

4. No emoji characters in cookbook Python files.

## Recommended Skeleton

```python
"""
<Title>
<What this demonstrates>
"""

# ---------------------------------------------------------------------------
# <Config / Setup>
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """..."""

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
example_agent = Agent(...)

# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    example_agent.print_response("...", stream=True)
```

## Validation

Run structure checks:

```bash
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/00_quickstart
```

Run metadata checks:

```bash
.venvs/demo/bin/python cookbook/scripts/audit_cookbook_metadata.py --scope direct
```
