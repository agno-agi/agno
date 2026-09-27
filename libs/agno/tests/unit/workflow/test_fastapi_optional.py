"""Regression tests: ``agno.workflow`` must work without ``fastapi`` installed.

fastapi only ships with the ``os`` extra, so a bare ``pip install agno`` must
still be able to import the package, build and run a workflow, and import
``RemoteWorkflow``. The websocket parameters on the async run methods are
annotated with fastapi's ``WebSocket``; the modules bind that name loosely at
runtime so ``get_type_hints()`` -- and with it ``Function.from_callable()`` --
keeps working whether or not fastapi is installed.

The no-fastapi cases run in a subprocess with ``fastapi`` masked in
``sys.modules``, which is deterministic across environments (the CI test env
has fastapi installed transitively via the dev extra).
"""

import subprocess
import sys
import textwrap
from typing import get_type_hints

import pytest


def _run_masked(code: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"subprocess failed. stdout={result.stdout!r} stderr={result.stderr!r}"
    assert result.stdout.strip() == "OK"


def test_workflow_usable_without_fastapi():
    """Import, construct, run, and introspect a workflow with fastapi masked."""
    code = textwrap.dedent(
        """
        import sys
        # Mask fastapi so any attempt to import it raises ModuleNotFoundError.
        sys.modules["fastapi"] = None  # type: ignore[assignment]

        from typing import get_type_hints

        from agno.workflow import RemoteWorkflow, Step, StepOutput, Workflow

        def hello(step_input):
            return StepOutput(content="hello")

        wf = Workflow(name="no-fastapi", steps=[Step(name="hello", executor=hello)])
        result = wf.run(input="hi")
        assert result.content == "hello"

        # The websocket annotations must resolve without fastapi.
        assert "websocket" in get_type_hints(Workflow.arun)
        assert "websocket" in get_type_hints(Workflow.acontinue_run)
        assert "websocket" in get_type_hints(RemoteWorkflow.arun)

        # Tool-schema generation walks those same annotations.
        from agno.tools.function import Function

        schema = Function.from_callable(wf.arun)
        assert schema.parameters["properties"]

        print("OK")
        """
    )
    _run_masked(code)


def test_import_does_not_load_fastapi():
    """Even with fastapi available, importing agno.workflow must not load it."""
    code = textwrap.dedent(
        """
        import sys

        import agno.workflow

        assert "fastapi" not in sys.modules, "import agno.workflow pulled in fastapi"
        print("OK")
        """
    )
    _run_masked(code)


def test_websocket_annotations_resolve_with_fastapi_installed():
    pytest.importorskip("fastapi", reason="dev/CI envs always have fastapi; bare envs are covered above")

    from agno.tools.function import Function
    from agno.workflow import Step, StepOutput, Workflow
    from agno.workflow.remote import RemoteWorkflow

    assert "websocket" in get_type_hints(Workflow.arun)
    assert "websocket" in get_type_hints(Workflow.acontinue_run)
    assert "websocket" in get_type_hints(RemoteWorkflow.arun)

    wf = Workflow(name="t", steps=[Step(name="s", executor=lambda si: StepOutput(content="x"))])
    schema = Function.from_callable(wf.arun)
    assert schema.parameters["properties"]
