import subprocess
import sys


BLOCK_FASTAPI_SCRIPT = """
import builtins

original_import = builtins.__import__


def block_fastapi(name, *args, **kwargs):
    if name == "fastapi" or name.startswith("fastapi."):
        raise ModuleNotFoundError("No module named 'fastapi'")
    return original_import(name, *args, **kwargs)


builtins.__import__ = block_fastapi
from agno.playground import Playground, PlaygroundSettings
assert Playground.__name__ == "Playground"
assert PlaygroundSettings().title == "agno-playground"
"""


def test_playground_import_exports_legacy_names_without_agentos_dependencies():
    result = subprocess.run(
        [sys.executable, "-c", BLOCK_FASTAPI_SCRIPT],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_playground_submodule_import_exports_same_aliases():
    from agno.playground import Playground, PlaygroundSettings
    from agno.playground.playground import Playground as SubmodulePlayground
    from agno.playground.playground import PlaygroundSettings as SubmodulePlaygroundSettings

    assert SubmodulePlayground is Playground
    assert SubmodulePlaygroundSettings is PlaygroundSettings
