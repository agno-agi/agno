"""The public surface of the agno.tools.file and agno.tools.knowledge packages.

Both were flat modules before; these pin the names callers already import from those paths,
the lazy resolution that keeps reportlab off the FileTools import, and the old
agno.tools.file_generation path.
"""

import subprocess
import sys

import pytest


def test_file_package_exports_both_toolkits_and_its_constants():
    from agno.tools.file import (
        CODE_LANGUAGE_MAP,
        DEFAULT_EXCLUDE_PATTERNS,
        DOCX_AVAILABLE,
        PDF_AVAILABLE,
        TEXT_EXTENSIONS,
        FileGenerationTools,
        FileTools,
        path_matches_exclude,
    )

    assert FileTools.__name__ == "FileTools"
    assert FileGenerationTools.__name__ == "FileGenerationTools"
    assert ".venv" in DEFAULT_EXCLUDE_PATTERNS
    assert ".md" in TEXT_EXTENSIONS
    assert "python" in CODE_LANGUAGE_MAP
    assert isinstance(PDF_AVAILABLE, bool) and isinstance(DOCX_AVAILABLE, bool)
    assert callable(path_matches_exclude)


def test_knowledge_package_exports_both_toolkits():
    from agno.tools.knowledge import KnowledgeManagementTools, KnowledgeTools

    assert KnowledgeTools.__name__ == "KnowledgeTools"
    assert KnowledgeManagementTools.__name__ == "KnowledgeManagementTools"


@pytest.mark.parametrize("module_name", ["agno.tools.file", "agno.tools.knowledge"])
def test_every_name_in_all_resolves(module_name):
    import importlib

    module = importlib.import_module(module_name)
    for name in module.__all__:
        assert getattr(module, name) is not None
    assert set(module.__all__) <= set(dir(module))
    with pytest.raises(AttributeError):
        module.NoSuchToolkit


def test_old_file_generation_path_is_the_same_class():
    from agno.tools.file import FileGenerationTools
    from agno.tools.file_generation import FileGenerationTools as Legacy

    assert Legacy is FileGenerationTools


@pytest.mark.parametrize(
    "statement, unwanted",
    [
        ("import agno.tools.file", "agno.tools.file.generation"),
        ("from agno.tools.file import FileTools", "agno.tools.file.generation"),
        ("import agno.tools.knowledge", "agno.tools.knowledge.management"),
    ],
)
def test_package_import_does_not_pull_the_sibling_toolkit(statement, unwanted):
    # FileGenerationTools drags reportlab and python-docx in with it; nothing that imports
    # FileTools should pay for that. Run out-of-process so an earlier test cannot mask it.
    code = f"{statement}\nimport sys\nassert '{unwanted}' not in sys.modules, '{unwanted} was imported eagerly'\n"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
