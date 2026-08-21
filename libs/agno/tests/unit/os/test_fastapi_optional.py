"""Regression tests: the remote client stack must work without ``fastapi`` installed.

fastapi only ships with the ``os`` extra, so a bare ``pip install agno`` must be
able to instantiate RemoteAgent, RemoteTeam, and RemoteWorkflow -- each of which
builds an AgentOSClient, importing ``agno.client.os`` and with it the response
schema modules under ``agno.os``. Those modules bind fastapi's ``UploadFile``
loosely at runtime so ``get_type_hints()`` -- and with it
``Function.from_callable()`` -- keeps working whether or not fastapi is
installed, and the ``agno.os`` package inits resolve the app and routers
lazily so the schema modules never pull fastapi in transitively.

The no-fastapi cases run in a subprocess with ``fastapi`` masked in
``sys.modules``, which is deterministic across environments (the CI test env
has fastapi installed transitively via the dev extra).
"""

import subprocess
import sys
import textwrap
from io import BytesIO
from typing import get_type_hints
from unittest.mock import AsyncMock

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


def test_remote_classes_usable_without_fastapi():
    """Instantiate all three remote classes and introspect the client with fastapi masked."""
    code = textwrap.dedent(
        """
        import sys
        # Mask fastapi so any attempt to import it raises ModuleNotFoundError.
        sys.modules["fastapi"] = None  # type: ignore[assignment]

        from typing import get_type_hints

        from agno.agent import RemoteAgent
        from agno.team import RemoteTeam
        from agno.workflow import RemoteWorkflow

        # Instantiation builds an AgentOSClient, which imports agno.client.os
        # and the response schema modules under agno.os.
        RemoteAgent(base_url="http://localhost:7777", agent_id="agent-1")
        RemoteTeam(base_url="http://localhost:7777", team_id="team-1")
        RemoteWorkflow(base_url="http://localhost:7777", workflow_id="workflow-1")

        # The upload annotations must resolve without fastapi.
        from agno.client import AgentOSClient

        assert "file" in get_type_hints(AgentOSClient.upload_knowledge_content)

        # Tool-schema generation walks those same annotations.
        from agno.tools.function import Function

        schema = Function.from_callable(AgentOSClient.upload_knowledge_content)
        assert schema.parameters["properties"]

        print("OK")
        """
    )
    _run_masked(code)


def test_schema_modules_import_without_fastapi():
    """The response schema modules the client depends on must not pull in fastapi."""
    code = textwrap.dedent(
        """
        import sys
        sys.modules["fastapi"] = None  # type: ignore[assignment]

        import agno.os.routers.agents.schema
        import agno.os.routers.evals.schemas
        import agno.os.routers.knowledge.schemas
        import agno.os.routers.memory.schemas
        import agno.os.routers.metrics.schemas
        import agno.os.routers.teams.schema
        import agno.os.routers.traces.schemas
        import agno.os.routers.workflows.schema
        import agno.os.schema
        import agno.os.schema_utils

        print("OK")
        """
    )
    _run_masked(code)


def test_import_agno_client_does_not_load_fastapi():
    """Even with fastapi available, importing agno.client must not load it."""
    code = textwrap.dedent(
        """
        import sys

        import agno.client

        assert "fastapi" not in sys.modules, "import agno.client pulled in fastapi"
        assert "agno.os.app" not in sys.modules, "import agno.client pulled in the AgentOS app"
        print("OK")
        """
    )
    _run_masked(code)


def test_upload_annotations_resolve_with_fastapi_installed():
    pytest.importorskip("fastapi", reason="dev/CI envs always have fastapi; bare envs are covered above")

    from agno.client import AgentOSClient
    from agno.tools.function import Function

    assert "file" in get_type_hints(AgentOSClient.upload_knowledge_content)
    schema = Function.from_callable(AgentOSClient.upload_knowledge_content)
    assert schema.parameters["properties"]


async def test_upload_content_builds_multipart_for_both_file_types():
    """The upload path must route agno File and fastapi UploadFile to the right multipart tuple."""
    fastapi = pytest.importorskip("fastapi", reason="dev/CI envs always have fastapi; bare envs are covered above")

    from agno.client import AgentOSClient
    from agno.media import File

    client = AgentOSClient(base_url="http://localhost:7777")
    client._apost_multipart = AsyncMock(return_value={"id": "content-1"})  # type: ignore[method-assign]

    # agno.media.File with content is sent as (filename, content, mime_type)
    await client.upload_knowledge_content(file=File(content=b"agno bytes", filename="a.txt", mime_type="text/plain"))
    files = client._apost_multipart.call_args.kwargs["files"]
    assert files == {"file": ("a.txt", b"agno bytes", "text/plain")}

    # fastapi UploadFile is sent as (filename, file object, content_type)
    upload = fastapi.UploadFile(file=BytesIO(b"fastapi bytes"), filename="b.txt")
    await client.upload_knowledge_content(file=upload)
    files = client._apost_multipart.call_args.kwargs["files"]
    assert files == {"file": ("b.txt", upload.file, "application/octet-stream")}

    # agno.media.File without content yields no files payload
    await client.upload_knowledge_content(file=File(url="http://example.com/c.txt"), name="c")
    assert client._apost_multipart.call_args.kwargs["files"] is None
