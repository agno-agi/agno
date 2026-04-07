# Workflow Visualization

Generate Mermaid flowcharts from Agno workflows. Every step type is supported: Step, Steps, Condition, Router, Loop, and Parallel.

## Overview

| Feature | Details |
|---------|---------|
| **Mermaid source** | Always available, zero extra dependencies |
| **SVG export** | Requires `pip install agno[visualize]` |
| **PNG export** | Requires `pip install agno[visualize]` |
| **Image viewer** | Opens in default OS viewer via `show()` |
| **Directions** | `"TD"` (top-down) or `"LR"` (left-right) |
| **Color flavors** | `"default"`, `"monotone"`, `"black"` |

## Quick Start

```python
from agno.workflow import Workflow, Step, Condition, Loop, Parallel, Router

workflow = Workflow(
    name="My Pipeline",
    steps=[...],
)

viz = workflow.visualize()
print(viz.to_mermaid())
```

## Install

Mermaid text generation works out of the box. For SVG/PNG/viewer rendering:

```bash
pip install agno[visualize]
```

This installs `mermaid-py` (renders via mermaid.ink API) and `Pillow` (for `show()`).

## Export Methods

```python
viz = workflow.visualize()

# Raw Mermaid source (always works, no network needed)
mermaid_text = viz.to_mermaid()

# Save to SVG file
viz.to_svg("workflow.svg")

# Save to PNG file
viz.to_png("workflow.png")

# Open in default image viewer
viz.show()
```

All file-export methods return the resolved `Path` of the written file.

## Customization

### Direction

Control the flow direction of the diagram:

```python
# Top-down (default)
viz = workflow.visualize(direction="TD")

# Left-right
viz = workflow.visualize(direction="LR")
```

### Color Flavors

Three built-in palettes:

```python
# Colorful (default) — blue steps, yellow conditions, green loops
viz = workflow.visualize(color="default")

# Grayscale — clean, print-friendly
viz = workflow.visualize(color="monotone")

# Dark theme — dark backgrounds, bright accents
viz = workflow.visualize(color="black")
```

Combine both options:

```python
viz = workflow.visualize(direction="LR", color="black")
```

List available flavors programmatically:

```python
from agno.visualize import AVAILABLE_FLAVORS

print(AVAILABLE_FLAVORS)  # ['default', 'monotone', 'black']
```

## Supported Step Types

Each step type renders with a distinct Mermaid shape:

| Step Type | Shape | Description |
|-----------|-------|-------------|
| `Step` | Rectangle | Atomic unit with an agent, team, or executor |
| `Steps` | Subgraph | Sequential container — children chained top-to-bottom |
| `Condition` | Diamond | If/else branching with "Yes"/"No" edges and a merge node |
| `Router` | Diamond | Multi-way dispatch — each choice gets a labeled edge |
| `Loop` | Subgraph (rounded) | Iterative block with an "End condition?" check node |
| `Parallel` | Subgraph | Fork/Join — branches run concurrently |
| Callable | Trapezoid | Raw Python function used as a step |

## Architecture

The visualize module lives at `agno.visualize` and is designed to extend beyond workflows:

```
agno/visualize/
    __init__.py      # Public API: WorkflowVisualization, generate_mermaid, AVAILABLE_FLAVORS
    _themes.py       # Color palettes (default, monotone, black)
    _utils.py        # Shared helpers: _IdCounter, _SHAPE, _sanitize
    _renderer.py     # WorkflowVisualization class (to_mermaid, to_svg, to_png, show)
    workflow.py      # Workflow-specific Mermaid generation logic
```

## Examples

- [visualize_workflow.py](visualize_workflow.py) — builds a workflow with every step type (Router, Parallel, Condition, Loop, Step) and exports the diagram in all formats
