"""
Unit tests for the asqav observability cookbook example.

Validates that the integration pattern in
cookbook/92_integrations/observability/asqav_via_openinference.py
uses the correct Agno APIs for OpenTelemetry-based observability.
"""

import ast
import os

import pytest


COOKBOOK_PATH = os.path.realpath(
    os.path.join(
        os.path.dirname(os.path.realpath(__file__)),
        "..",
        "..",
        "..",
        "..",
        "..",
        "cookbook",
        "92_integrations",
        "observability",
        "asqav_via_openinference.py",
    )
)


def test_cookbook_file_exists():
    """The asqav cookbook example file must exist."""
    assert os.path.isfile(COOKBOOK_PATH), f"Missing cookbook file: {COOKBOOK_PATH}"


def test_cookbook_file_parses():
    """The cookbook example must be valid Python."""
    with open(COOKBOOK_PATH) as f:
        source = f.read()
    # ast.parse raises SyntaxError on invalid Python
    tree = ast.parse(source)
    assert tree is not None


def test_cookbook_imports_agno_agent():
    """The cookbook example must import agno.agent.Agent."""
    with open(COOKBOOK_PATH) as f:
        source = f.read()
    tree = ast.parse(source)

    agno_imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and "agno" in node.module:
            for alias in node.names:
                agno_imports.append(f"{node.module}.{alias.name}")

    assert any("agno.agent" in imp for imp in agno_imports), (
        f"Expected agno.agent import, found: {agno_imports}"
    )


def test_cookbook_imports_openinference():
    """The cookbook example must import AgnoInstrumentor."""
    with open(COOKBOOK_PATH) as f:
        source = f.read()
    tree = ast.parse(source)

    oi_imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and "openinference" in node.module:
            for alias in node.names:
                oi_imports.append(alias.name)

    assert "AgnoInstrumentor" in oi_imports, (
        f"Expected AgnoInstrumentor import, found: {oi_imports}"
    )


def test_cookbook_imports_asqav():
    """The cookbook example must import asqav."""
    with open(COOKBOOK_PATH) as f:
        source = f.read()
    tree = ast.parse(source)

    has_asqav = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "asqav":
                    has_asqav = True
        elif isinstance(node, ast.ImportFrom) and node.module and "asqav" in node.module:
            has_asqav = True

    assert has_asqav, "Expected asqav import in cookbook example"


def test_cookbook_has_main_guard():
    """The cookbook example must have an if __name__ == '__main__' guard."""
    with open(COOKBOOK_PATH) as f:
        source = f.read()
    assert '__name__' in source and '__main__' in source, (
        "Cookbook example should have a __main__ guard"
    )
