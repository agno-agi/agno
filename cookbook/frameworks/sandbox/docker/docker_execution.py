"""Run without model credentials: python cookbook/frameworks/sandbox/docker/docker_execution.py."""

import os
from uuid import uuid4

from agno.sandbox.docker import DockerSandbox

sandbox = DockerSandbox(
    image=os.environ.get("AGNO_SANDBOX_IMAGE", "python:3.12-slim"),
    namespace="cookbook-" + uuid4().hex,
    memory_mb=256,
)
handle = sandbox.create(session_id="example")
try:
    result = sandbox.exec(
        handle,
        [
            "python",
            "-c",
            "from pathlib import Path; Path('hello.txt').write_text('hello')",
        ],
    )
    assert result.exit_code == 0, result.stderr
    result = sandbox.exec(handle, ["cat", "hello.txt"])
    assert result.stdout == "hello"
    # Creating the same session again returns the running container instead of a new one.
    assert sandbox.create(session_id="example").provider_ref == handle.provider_ref
    print("Created and reused a sandbox, wrote and read a workspace file.")
finally:
    sandbox.destroy(handle)
