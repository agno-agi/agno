"""Run without model credentials. This creates billable compute on Agent 37.

Set AGENT37_API_KEY to a key from the Agent 37 dashboard, then:

    .venv/bin/python cookbook/frameworks/sandbox/agent37/agent37_execution.py

The default agent37-base template needs no setup: any template with python3 works.
"""

import os
from uuid import uuid4

from agno.sandbox.agent37 import Agent37Sandbox

sandbox = Agent37Sandbox(
    template=os.environ.get("AGENT37_TEMPLATE", "agent37-base"),
    namespace="cookbook-" + uuid4().hex,
)
env = {"GREETING": "hello"}
handle = sandbox.create(session_id="example", env=env)
try:
    result = sandbox.exec(
        handle, ["sh", "-c", 'printf "$GREETING" > hello.txt; id -u; pwd']
    )
    assert result.exit_code == 0, result.stderr
    # Commands run as UID 1000 in /workspace, whatever user the template's image declares.
    assert result.stdout.split() == ["1000", "/workspace"], result.stdout
    result = sandbox.exec(handle, ["cat", "hello.txt"])
    assert result.stdout == "hello", result
    # Creating the same session again returns the running instance instead of a new one.
    again = sandbox.create(session_id="example", env=env)
    assert again.provider_ref == handle.provider_ref
    # Pause puts the instance to sleep at disk-only cost; resume wakes the same generation.
    sandbox.pause(handle)
    assert sandbox.get(handle.provider_ref).state == "paused"
    handle = sandbox.resume(handle)
    assert sandbox.exec(handle, ["cat", "hello.txt"]).stdout == "hello"
    print("Created, reused, paused and resumed a sandbox; wrote and read a file.")
finally:
    sandbox.destroy(handle)
