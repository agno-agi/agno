"""Workflow-specific Mermaid flowchart generation."""

from __future__ import annotations

from typing import Any, Optional, Sequence

from agno.visualize._themes import COLOR_FLAVORS
from agno.visualize._utils import _SHAPE, _IdCounter, _sanitize

# ---------------------------------------------------------------------------
# Recursive Mermaid generation
# ---------------------------------------------------------------------------


def _get_step_label(step: Any) -> str:
    """Build a human-readable label for a Step node."""
    from agno.workflow.step import Step

    if not isinstance(step, Step):
        return getattr(step, "name", None) or "Step"

    parts: list[str] = []
    name = step.name or "Step"
    parts.append(name)

    if step.agent is not None:
        agent_name = getattr(step.agent, "name", None) or "Agent"
        parts.append(f"agent: {agent_name}")
    elif step.team is not None:
        team_name = getattr(step.team, "name", None) or "Team"
        parts.append(f"team: {team_name}")
    elif step.executor is not None:
        fn_name = getattr(step.executor, "__name__", "function")
        parts.append(f"fn: {fn_name}")

    if len(parts) == 1:
        return _sanitize(parts[0])
    return f"{_sanitize(parts[0])}<br/>{_sanitize(parts[1])}"


def _emit_step(
    step: Any,
    lines: list[str],
    ids: _IdCounter,
    classes: list[str],
) -> tuple[str, str]:
    """Emit Mermaid nodes/edges for a single step-tree node.

    Returns ``(first_node_id, last_node_id)`` so parent can wire edges.
    """
    from agno.workflow.condition import Condition
    from agno.workflow.loop import Loop
    from agno.workflow.parallel import Parallel
    from agno.workflow.router import Router
    from agno.workflow.step import Step
    from agno.workflow.steps import Steps

    # --- Callable (raw function) ---
    if callable(step) and not isinstance(step, (Step, Steps, Loop, Parallel, Condition, Router)):
        nid = ids.next()
        fn_name = getattr(step, "__name__", "function")
        lp, rp = _SHAPE["callable"]
        lines.append(f'    {nid}{lp}"{_sanitize(fn_name)}"{rp}')
        classes.append(f"class {nid} callableStyle")
        return nid, nid

    # --- Step (atomic) ---
    if isinstance(step, Step):
        nid = ids.next()
        label = _get_step_label(step)
        lp, rp = _SHAPE["step"]
        lines.append(f'    {nid}{lp}"{label}"{rp}')
        classes.append(f"class {nid} stepStyle")
        return nid, nid

    # --- Steps (sequential container) ---
    if isinstance(step, Steps):
        sg_id = ids.next("sg")
        name = _sanitize(step.name or "Sequential Steps")
        lines.append(f'    subgraph {sg_id}["{name}"]')
        lines.append("    direction TB")
        prev_last: Optional[str] = None
        first_id: Optional[str] = None

        for child in step.steps:
            cfirst, clast = _emit_step(child, lines, ids, classes)
            if first_id is None:
                first_id = cfirst
            if prev_last is not None:
                lines.append(f"    {prev_last} --> {cfirst}")
            prev_last = clast

        lines.append("    end")
        classes.append(f"class {sg_id} stepsStyle")
        return first_id or sg_id, prev_last or sg_id

    # --- Condition ---
    if isinstance(step, Condition):
        cond_id = ids.next()
        name = _sanitize(step.name or "Condition")
        lp, rp = _SHAPE["condition"]
        lines.append(f'    {cond_id}{lp}"{name}"{rp}')
        classes.append(f"class {cond_id} conditionStyle")

        # If-branch
        if step.steps:
            if_first, if_last = _emit_chain(step.steps, lines, ids, classes)
            lines.append(f'    {cond_id} -->|"Yes"| {if_first}')
        else:
            if_last = cond_id

        # Else-branch
        if step.else_steps:
            else_first, else_last = _emit_chain(step.else_steps, lines, ids, classes)
            lines.append(f'    {cond_id} -->|"No"| {else_first}')
        else:
            else_last = None

        # Merge node
        merge_id = ids.next()
        lines.append(f'    {merge_id}((" "))')
        classes.append(f"class {merge_id} conditionStyle")
        if if_last and if_last != cond_id:
            lines.append(f"    {if_last} --> {merge_id}")
        if else_last:
            lines.append(f"    {else_last} --> {merge_id}")
        elif not step.else_steps:
            lines.append(f'    {cond_id} -->|"No"| {merge_id}')

        return cond_id, merge_id

    # --- Router ---
    if isinstance(step, Router):
        router_id = ids.next()
        name = _sanitize(step.name or "Router")
        lp, rp = _SHAPE["router"]
        lines.append(f'    {router_id}{lp}"{name}"{rp}')
        classes.append(f"class {router_id} routerStyle")

        merge_id = ids.next()
        lines.append(f'    {merge_id}((" "))')
        classes.append(f"class {merge_id} routerStyle")

        for choice in step.choices or []:
            choice_name = _get_choice_label(choice)
            cfirst, clast = _emit_step(choice, lines, ids, classes)
            lines.append(f'    {router_id} -->|"{_sanitize(choice_name)}"| {cfirst}')
            lines.append(f"    {clast} --> {merge_id}")

        return router_id, merge_id

    # --- Loop ---
    if isinstance(step, Loop):
        sg_id = ids.next("sg")
        name = _sanitize(step.name or "Loop")
        max_iter = step.max_iterations
        lines.append(f'    subgraph {sg_id}["{name} #lpar;max {max_iter}#rpar;"]')
        lines.append("    direction TB")

        if step.steps:
            chain_first, chain_last = _emit_chain(step.steps, lines, ids, classes)
        else:
            chain_first = chain_last = sg_id

        # End-condition check node
        check_id = ids.next()
        lines.append(f'    {check_id}{{"End condition?"}}')
        classes.append(f"class {check_id} loopStyle")
        lines.append(f"    {chain_last} --> {check_id}")
        lines.append(f'    {check_id} -->|"Continue"| {chain_first}')

        lines.append("    end")
        classes.append(f"class {sg_id} loopStyle")

        # Exit edge goes from check node outward — handled by caller via last_id
        return chain_first, check_id

    # --- Parallel ---
    if isinstance(step, Parallel):
        sg_id = ids.next("sg")
        name = _sanitize(step.name or "Parallel")
        lines.append(f'    subgraph {sg_id}["{name}"]')
        lines.append("    direction TB")

        fork_id = ids.next()
        join_id = ids.next()
        lines.append(f'    {fork_id}(("Fork"))')
        lines.append(f'    {join_id}(("Join"))')
        classes.append(f"class {fork_id} parallelStyle")
        classes.append(f"class {join_id} parallelStyle")

        for branch in step.steps or []:
            bfirst, blast = _emit_step(branch, lines, ids, classes)
            lines.append(f"    {fork_id} --> {bfirst}")
            lines.append(f"    {blast} --> {join_id}")

        lines.append("    end")
        classes.append(f"class {sg_id} parallelStyle")
        return fork_id, join_id

    # Fallback — treat unknown as opaque node
    nid = ids.next()
    label = _sanitize(str(getattr(step, "name", step)))
    lines.append(f'    {nid}["{label}"]')
    return nid, nid


def _emit_chain(
    steps: Sequence[Any],
    lines: list[str],
    ids: _IdCounter,
    classes: list[str],
) -> tuple[str, str]:
    """Emit a linear chain of steps and return ``(first_id, last_id)``."""
    prev_last: Optional[str] = None
    first_id: Optional[str] = None

    for child in steps:
        cfirst, clast = _emit_step(child, lines, ids, classes)
        if first_id is None:
            first_id = cfirst
        if prev_last is not None:
            lines.append(f"    {prev_last} --> {cfirst}")
        prev_last = clast

    return first_id or "?", prev_last or "?"


def _get_choice_label(choice: Any) -> str:
    """Get a short label for a Router choice edge."""
    from agno.workflow.step import Step

    if isinstance(choice, Step):
        return choice.name or "Step"
    if callable(choice):
        return getattr(choice, "__name__", "function")
    return getattr(choice, "name", None) or "choice"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_mermaid(
    steps: Any,
    workflow_name: Optional[str] = None,
    direction: str = "TD",
    color: str = "default",
) -> str:
    """Generate a Mermaid flowchart string from workflow steps.

    Args:
        steps: The workflow ``steps`` attribute (list or callable).
        workflow_name: Optional name shown in the title.
        direction: Mermaid direction — ``"TD"`` (top-down) or ``"LR"`` (left-right).
        color: Color flavor — ``"default"``, ``"monotone"``, or ``"black"``.

    Returns:
        Complete Mermaid flowchart source text.
    """
    style_defs = COLOR_FLAVORS.get(color, COLOR_FLAVORS["default"])
    lines: list[str] = []
    classes: list[str] = []
    ids = _IdCounter()

    lines.append(f"flowchart {direction}")

    # Start node
    start_id = ids.next()
    lines.append(f'    {start_id}(["Start"])')
    classes.append(f"class {start_id} startEnd")

    if steps is None:
        end_id = ids.next()
        lines.append(f'    {end_id}(["End"])')
        classes.append(f"class {end_id} startEnd")
        lines.append(f"    {start_id} --> {end_id}")
    elif callable(steps):
        fn_name = getattr(steps, "__name__", "run")
        nid = ids.next()
        lp, rp = _SHAPE["callable"]
        lines.append(f'    {nid}{lp}"{_sanitize(fn_name)}"{rp}')
        classes.append(f"class {nid} callableStyle")
        end_id = ids.next()
        lines.append(f'    {end_id}(["End"])')
        classes.append(f"class {end_id} startEnd")
        lines.append(f"    {start_id} --> {nid}")
        lines.append(f"    {nid} --> {end_id}")
    elif isinstance(steps, list):
        chain_first, chain_last = _emit_chain(steps, lines, ids, classes)
        end_id = ids.next()
        lines.append(f'    {end_id}(["End"])')
        classes.append(f"class {end_id} startEnd")
        lines.append(f"    {start_id} --> {chain_first}")
        lines.append(f"    {chain_last} --> {end_id}")
    else:
        # Single step object (e.g. Steps instance at top level)
        sfirst, slast = _emit_step(steps, lines, ids, classes)
        end_id = ids.next()
        lines.append(f'    {end_id}(["End"])')
        classes.append(f"class {end_id} startEnd")
        lines.append(f"    {start_id} --> {sfirst}")
        lines.append(f"    {slast} --> {end_id}")

    # Append style definitions and class assignments
    lines.append("")
    lines.extend(f"    {sd}" for sd in style_defs)
    lines.append("")
    lines.extend(f"    {c}" for c in classes)

    return "\n".join(lines) + "\n"
