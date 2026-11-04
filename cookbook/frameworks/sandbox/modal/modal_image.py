"""The shared runtime image, built on Modal from the same Dockerfile that Docker and AgentCore use.

Imported by the other cookbooks in this folder. Only public package sources go into the build
context, as with build_image.py; the working tree is never sent. Modal caches the build, so
later runs with unchanged sources reuse it.
"""

import atexit
import shutil
import tempfile
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[4]


def runtime_image() -> modal.Image:
    # A context per process, so cookbooks running at once never share one; Modal caches by content.
    context = Path(tempfile.mkdtemp(prefix="agno-modal-context-"))
    atexit.register(shutil.rmtree, context, ignore_errors=True)
    shutil.copytree(
        ROOT / "libs/agno/agno",
        context / "agno",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    for filename in ("pyproject.toml", "LICENSE"):
        shutil.copyfile(ROOT / "libs/agno" / filename, context / filename)
    shutil.copyfile(ROOT / "README.md", context / "README.md")
    shutil.copyfile(Path(__file__).parents[1] / "Dockerfile", context / "Dockerfile")
    # The image's entrypoint is the AgentCore server; Modal sandboxes run their own command instead.
    return modal.Image.from_dockerfile(
        context / "Dockerfile", context_dir=context
    ).entrypoint([])
