"""Exercise runtime reconnect/idempotency without model credentials."""

import os
from uuid import uuid4

from agno.sandbox.client import SandboxRuntimeClient
from agno.sandbox.docker import DockerSandbox

provider = DockerSandbox(
    image=os.environ.get("AGNO_SANDBOX_IMAGE", "agno-sandbox:local"),
    namespace="runtime-cookbook-" + uuid4().hex,
    memory_mb=512,
)
computer = provider.create(
    session_id="example", agent_id="coder", env={"AGNO_SANDBOX_TEST_RUNTIME": "1"}
)
try:
    first = SandboxRuntimeClient(provider)
    execution = first.start(
        computer,
        execution_id="execution-1",
        run_id="run-1",
        sdk="fixture",
        input="hello",
    )
    # A different client recovers a lost start acknowledgement using the same identity.
    second = SandboxRuntimeClient(
        DockerSandbox(provider.image, namespace=provider.namespace, memory_mb=512)
    )
    assert (
        second.start(
            computer,
            execution_id="execution-1",
            run_id="run-1",
            sdk="fixture",
            input="hello",
        )
        == execution
    )
    result = second.wait_result(execution, timeout=30)
    assert result["type"] == "execution_finished"
    assert result["run"]["content"] == "hello"
    assert second.poll(execution, cursor=0).events[0]["content"] == "hello"
    assert provider.exec(computer, ["cat", "fixture-effects.txt"]).stdout == "run-1\n"
    print(
        "Reconnected, replayed events and received one execution result without repeating the effect."
    )
finally:
    provider.destroy(computer)
