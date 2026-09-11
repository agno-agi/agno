"""Workflow.__init__ is keyword-only.

Positional arguments would otherwise silently rebind whenever a parameter is
added mid-signature.
"""

import pytest

from agno.workflow import Workflow


def test_constructor_is_keyword_only():
    with pytest.raises(TypeError):
        Workflow("some-id")  # type: ignore[misc]


def test_keyword_construction_unchanged():
    workflow = Workflow(id="some-id", name="workflow")
    assert workflow.id == "some-id"
    assert workflow.name == "workflow"
