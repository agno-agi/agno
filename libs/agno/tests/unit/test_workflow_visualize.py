"""Unit tests for workflow visualization (Mermaid generation)."""

from __future__ import annotations

from agno.agent import Agent
from agno.visualize import DEFAULT_INK_SERVER, WorkflowVisualization, generate_mermaid
from agno.workflow import Condition, Loop, Parallel, Router, Step, Steps, Workflow

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Minimal agent used to satisfy Step's executor requirement
_agent = Agent(name="TestAgent", model="openai:gpt-4o-mini")


def _dummy_executor(step_input):
    pass


def _dummy_evaluator(step_input):
    return True


def _dummy_selector(step_input):
    return []


def _step(name: str, **kwargs) -> Step:
    """Create a Step with a default agent so the executor validation passes."""
    return Step(name=name, agent=kwargs.pop("agent", _agent), **kwargs)


# ---------------------------------------------------------------------------
# generate_mermaid — basic structure tests
# ---------------------------------------------------------------------------


class TestGenerateMermaid:
    def test_none_steps(self):
        result = generate_mermaid(None, workflow_name="Empty")
        assert "flowchart TD" in result
        assert "Start" in result
        assert "End" in result

    def test_callable_steps(self):
        result = generate_mermaid(_dummy_executor, workflow_name="Callable WF")
        assert "_dummy_executor" in result
        assert "Start" in result
        assert "End" in result

    def test_single_step(self):
        steps = [_step("Research")]
        result = generate_mermaid(steps, workflow_name="Basic")
        assert "Research" in result
        assert "Start" in result
        assert "End" in result

    def test_sequential_steps(self):
        steps = [
            _step("Research"),
            _step("Write"),
            _step("Review"),
        ]
        result = generate_mermaid(steps)
        assert "Research" in result
        assert "Write" in result
        assert "Review" in result
        # Should have edges between them
        assert "-->" in result

    def test_direction_lr(self):
        result = generate_mermaid([_step("A")], direction="LR")
        assert "flowchart LR" in result


# ---------------------------------------------------------------------------
# Step labels
# ---------------------------------------------------------------------------


class TestStepLabels:
    def test_step_with_agent(self):
        step = _step("Research")
        result = generate_mermaid([step])
        assert "Research" in result
        assert "TestAgent" in result

    def test_step_with_executor(self):
        step = Step(name="Custom", executor=_dummy_executor)
        result = generate_mermaid([step])
        assert "Custom" in result
        assert "_dummy_executor" in result


# ---------------------------------------------------------------------------
# Condition
# ---------------------------------------------------------------------------


class TestCondition:
    def test_condition_basic(self):
        steps = [
            Condition(
                name="Check Quality",
                evaluator=_dummy_evaluator,
                steps=[_step("Fix")],
            ),
        ]
        result = generate_mermaid(steps)
        assert "Check Quality" in result
        assert "Fix" in result
        assert "Yes" in result
        assert "No" in result

    def test_condition_with_else(self):
        steps = [
            Condition(
                name="Is Valid?",
                evaluator=True,
                steps=[_step("Proceed")],
                else_steps=[_step("Reject")],
            ),
        ]
        result = generate_mermaid(steps)
        assert "Is Valid?" in result
        assert "Proceed" in result
        assert "Reject" in result
        assert "Yes" in result
        assert "No" in result


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class TestRouter:
    def test_router_basic(self):
        steps = [
            Router(
                name="Smart Router",
                choices=[
                    _step("Route A"),
                    _step("Route B"),
                ],
                selector=_dummy_selector,
            ),
        ]
        result = generate_mermaid(steps)
        assert "Smart Router" in result
        assert "Route A" in result
        assert "Route B" in result

    def test_router_with_callable_choices(self):
        steps = [
            Router(
                name="Fn Router",
                choices=[_dummy_executor],
                selector=_dummy_selector,
            ),
        ]
        result = generate_mermaid(steps)
        assert "Fn Router" in result
        assert "_dummy_executor" in result


# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------


class TestLoop:
    def test_loop_basic(self):
        steps = [
            Loop(
                name="Refine Loop",
                steps=[_step("Draft"), _step("Review")],
                max_iterations=5,
            ),
        ]
        result = generate_mermaid(steps)
        assert "Refine Loop" in result
        assert "max 5" in result
        assert "Draft" in result
        assert "Review" in result
        assert "End condition?" in result
        assert "Continue" in result


# ---------------------------------------------------------------------------
# Parallel
# ---------------------------------------------------------------------------


class TestParallel:
    def test_parallel_basic(self):
        steps = [
            Parallel(
                _step("Branch A"),
                _step("Branch B"),
                _step("Branch C"),
                name="Fan Out",
            ),
        ]
        result = generate_mermaid(steps)
        assert "Fan Out" in result
        assert "Branch A" in result
        assert "Branch B" in result
        assert "Branch C" in result
        assert "Fork" in result
        assert "Join" in result


# ---------------------------------------------------------------------------
# Steps (sequential container)
# ---------------------------------------------------------------------------


class TestSteps:
    def test_steps_container(self):
        steps = [
            Steps(
                name="Pipeline",
                steps=[_step("Step 1"), _step("Step 2")],
            ),
        ]
        result = generate_mermaid(steps)
        assert "Pipeline" in result
        assert "Step 1" in result
        assert "Step 2" in result
        assert "subgraph" in result


# ---------------------------------------------------------------------------
# Nested compositions
# ---------------------------------------------------------------------------


class TestNestedComposition:
    def test_loop_containing_parallel(self):
        steps = [
            Loop(
                name="Outer Loop",
                steps=[
                    _step("Inner Step"),
                    Parallel(
                        _step("Para A"),
                        _step("Para B"),
                        name="Inner Parallel",
                    ),
                ],
                max_iterations=2,
            ),
        ]
        result = generate_mermaid(steps)
        assert "Outer Loop" in result
        assert "Inner Step" in result
        assert "Inner Parallel" in result
        assert "Para A" in result
        assert "Para B" in result

    def test_condition_inside_steps(self):
        steps = [
            Steps(
                name="Main Pipeline",
                steps=[
                    _step("Start Work"),
                    Condition(
                        name="Gate",
                        evaluator=True,
                        steps=[_step("Pass")],
                        else_steps=[_step("Fail")],
                    ),
                ],
            ),
        ]
        result = generate_mermaid(steps)
        assert "Main Pipeline" in result
        assert "Start Work" in result
        assert "Gate" in result
        assert "Pass" in result
        assert "Fail" in result


# ---------------------------------------------------------------------------
# WorkflowVisualization via Workflow.visualize()
# ---------------------------------------------------------------------------


class TestWorkflowVisualize:
    def test_visualize_returns_visualization(self):
        wf = Workflow(
            name="Test WF",
            steps=[_step("Only Step")],
        )
        viz = wf.visualize()
        assert isinstance(viz, WorkflowVisualization)

    def test_to_mermaid_returns_string(self):
        wf = Workflow(
            name="Test WF",
            steps=[_step("A"), _step("B")],
        )
        result = wf.visualize().to_mermaid()
        assert isinstance(result, str)
        assert "flowchart TD" in result
        assert "A" in result
        assert "B" in result

    def test_empty_workflow(self):
        wf = Workflow(name="Empty")
        result = wf.visualize().to_mermaid()
        assert "Start" in result
        assert "End" in result

    def test_repr(self):
        wf = Workflow(name="Repr Test", steps=[_step("X")])
        viz = wf.visualize()
        assert "WorkflowVisualization" in repr(viz)
        assert "Repr Test" in repr(viz)

    def test_str_returns_mermaid(self):
        wf = Workflow(name="Str Test", steps=[_step("X")])
        viz = wf.visualize()
        assert str(viz) == viz.to_mermaid()


# ---------------------------------------------------------------------------
# Style definitions are included
# ---------------------------------------------------------------------------


class TestStyling:
    def test_class_defs_present(self):
        result = generate_mermaid([_step("S")])
        assert "classDef stepStyle" in result
        assert "classDef conditionStyle" in result
        assert "classDef routerStyle" in result
        assert "classDef loopStyle" in result
        assert "classDef parallelStyle" in result

    def test_class_assignments_present(self):
        result = generate_mermaid([_step("S")])
        assert "class n" in result  # at least one class assignment

    def test_monotone_flavor(self):
        result = generate_mermaid([_step("S")], color="monotone")
        assert "classDef stepStyle fill:#f5f5f5" in result
        assert "#0288d1" not in result  # no default blue

    def test_black_flavor(self):
        result = generate_mermaid([_step("S")], color="black")
        assert "classDef stepStyle fill:#263238" in result
        assert "#e1f5fe" not in result  # no default light blue

    def test_unknown_flavor_falls_back_to_default(self):
        result = generate_mermaid([_step("S")], color="neon")
        assert "classDef stepStyle fill:#e1f5fe" in result

    def test_direction_lr(self):
        result = generate_mermaid([_step("A")], direction="LR")
        assert "flowchart LR" in result

    def test_workflow_visualize_with_color_and_direction(self):
        wf = Workflow(name="Custom", steps=[_step("X")])
        viz = wf.visualize(direction="LR", color="monotone")
        result = viz.to_mermaid()
        assert "flowchart LR" in result
        assert "fill:#f5f5f5" in result


# ---------------------------------------------------------------------------
# Import guard tests
# ---------------------------------------------------------------------------


class TestImportGuards:
    def test_to_mermaid_always_works(self):
        wf = Workflow(name="Guard", steps=[_step("X")])
        viz = wf.visualize()
        mermaid_text = viz.to_mermaid()
        assert len(mermaid_text) > 0


# ---------------------------------------------------------------------------
# Ink server configuration
# ---------------------------------------------------------------------------


class TestInkServer:
    def test_default_ink_server(self):
        assert DEFAULT_INK_SERVER == "https://mermaid.ink"

    def test_viz_uses_default_server(self):
        viz = WorkflowVisualization("flowchart TD\n    A-->B\n")
        assert viz._ink_server == "https://mermaid.ink"

    def test_viz_custom_ink_server(self):
        viz = WorkflowVisualization("flowchart TD\n    A-->B\n", ink_server="https://my-mermaid.example.com")
        assert viz._ink_server == "https://my-mermaid.example.com"

    def test_viz_strips_trailing_slash(self):
        viz = WorkflowVisualization("flowchart TD\n    A-->B\n", ink_server="https://my-mermaid.example.com/")
        assert viz._ink_server == "https://my-mermaid.example.com"

    def test_workflow_visualize_passes_ink_server(self):
        wf = Workflow(name="Ink Test", steps=[_step("X")])
        viz = wf.visualize(ink_server="https://custom.ink")
        assert viz._ink_server == "https://custom.ink"

    def test_env_var_fallback(self, monkeypatch):
        monkeypatch.setenv("MERMAID_INK_SERVER", "https://env-server.example.com")
        viz = WorkflowVisualization("flowchart TD\n    A-->B\n")
        assert viz._ink_server == "https://env-server.example.com"

    def test_explicit_overrides_env_var(self, monkeypatch):
        monkeypatch.setenv("MERMAID_INK_SERVER", "https://env-server.example.com")
        viz = WorkflowVisualization("flowchart TD\n    A-->B\n", ink_server="https://explicit.example.com")
        assert viz._ink_server == "https://explicit.example.com"
