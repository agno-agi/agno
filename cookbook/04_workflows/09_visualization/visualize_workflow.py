"""
Workflow Visualization
=====================

Demonstrates generating Mermaid diagrams from workflows using ``workflow.visualize()``.

Outputs:
- Mermaid source text (always available, zero extra deps)
- SVG file (requires ``pip install agno[visualize]``)
- PNG file (requires ``pip install agno[visualize]``)
- Opens in default image viewer (requires ``pip install agno[visualize]``)

Customization:
- direction: "TD" (top-down) or "LR" (left-right)
- color: "default", "monotone", or "black"
"""

from agno.agent import Agent
from agno.workflow import Condition, Loop, Parallel, Router, Step, Workflow

# ---------------------------------------------------------------------------
# Define Agents (lightweight — no API calls needed for visualization)
# ---------------------------------------------------------------------------
researcher = Agent(name="Researcher")
writer = Agent(name="Writer")
reviewer = Agent(name="Reviewer")
fact_checker = Agent(name="Fact Checker")
editor = Agent(name="Editor")


def needs_fact_check(step_input):
    """Dummy evaluator for the Condition."""
    return True


def pick_research_source(step_input):
    """Dummy selector for the Router."""
    return []


# ---------------------------------------------------------------------------
# Build a workflow with every step type
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="Content Pipeline",
    steps=[
        # Router: pick which research source to use
        Router(
            name="Research Router",
            choices=[
                Step(name="Research HackerNews", agent=researcher),
                Step(name="Research Web", agent=researcher),
            ],
            selector=pick_research_source,
        ),
        # Parallel: run analysis in parallel
        Parallel(
            Step(name="Sentiment Analysis", agent=researcher),
            Step(name="Trend Analysis", agent=researcher),
            name="Analysis Phase",
        ),
        # Condition: maybe fact-check
        Condition(
            name="Needs Fact Check?",
            evaluator=needs_fact_check,
            steps=[Step(name="Run Fact Check", agent=fact_checker)],
            else_steps=[Step(name="Skip to Edit", agent=editor)],
        ),
        # Loop: iterative refinement
        Loop(
            name="Refinement Loop",
            steps=[
                Step(name="Write Draft", agent=writer),
                Step(name="Review Draft", agent=reviewer),
            ],
            max_iterations=3,
        ),
        # Final step
        Step(name="Publish", agent=editor),
    ],
)


if __name__ == "__main__":
    viz = workflow.visualize()

    # 1) Print Mermaid source (always works)
    print("=== Mermaid Source (default colors, top-down) ===")
    print(viz.to_mermaid())

    # 2) Export to SVG
    try:
        path = viz.to_svg("workflow_output.svg")
        print(f"SVG saved to: {path}")
    except ImportError as e:
        print(f"SVG export skipped: {e}")

    # 3) Export to PNG
    try:
        path = viz.to_png("workflow_output.png")
        print(f"PNG saved to: {path}")
    except ImportError as e:
        print(f"PNG export skipped: {e}")

    # 4) Open in default image viewer
    try:
        viz.show()
    except Exception as e:
        print(f"Display skipped: {e}")

    # 5) Try different color flavors and directions
    for color in ["monotone", "black"]:
        v = workflow.visualize(color=color)
        print(f"\n=== {color.title()} Color ===")
        try:
            path = v.to_png(f"workflow_{color}.png")
            print(f"PNG saved to: {path}")
        except ImportError as e:
            print(f"PNG export skipped: {e}")

    # 6) Left-right layout
    v_lr = workflow.visualize(direction="LR", color="default")
    print("\n=== Left-Right Layout ===")
    try:
        path = v_lr.to_png("workflow_lr.png")
        print(f"PNG saved to: {path}")
    except ImportError as e:
        print(f"PNG export skipped: {e}")
