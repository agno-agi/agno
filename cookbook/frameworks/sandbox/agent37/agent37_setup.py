"""Build or remove the Agent 37 template for sandboxed agents. Builds are free; instances are not.

Agent 37 builds the runtime image in its cloud from this folder's parent Dockerfile and
the public package sources, so no local Docker or registry is needed:

  .venv/bin/python cookbook/frameworks/sandbox/agent37/agent37_setup.py deploy --name agno-sandbox
  .venv/bin/python cookbook/frameworks/sandbox/agent37/agent37_setup.py teardown --name agno-sandbox

Set AGENT37_API_KEY first. Deploy prints the template name to pass to Agent37Sandbox.
Building again under the same name publishes a new revision; instances created
afterwards use it.
"""

import argparse
import os
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

API = "https://api.agent37.com/v1"
# The image's own entrypoint is the AgentCore server. An Agent 37 instance only needs a main
# process that stays up: commands reach it through the exec API.
ENTRYPOINT = ["sleep", "infinity"]


def pack_context(destination: Path) -> None:
    """Only the public package sources and the Dockerfile; never the working tree."""
    root = Path(__file__).resolve().parents[4]

    def keep(info: tarfile.TarInfo) -> Optional[tarfile.TarInfo]:
        name = Path(info.name).name
        return None if name == "__pycache__" or name.endswith(".pyc") else info

    with tarfile.open(destination, "w:gz") as archive:
        archive.add(root / "libs/agno/agno", arcname="agno", filter=keep)
        for filename in ("pyproject.toml", "LICENSE"):
            archive.add(root / "libs/agno" / filename, arcname=filename)
        archive.add(root / "README.md", arcname="README.md")
        archive.add(
            Path(__file__).resolve().parent.parent / "Dockerfile", arcname="Dockerfile"
        )


def call(client: httpx.Client, method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
    response = client.request(method, API + path, **kwargs)
    if response.status_code >= 300:
        raise SystemExit(
            f"Agent 37 refused {method} {path}: {response.status_code} {response.text[:1000]}"
        )
    return response.json()


def deploy(client: httpx.Client, name: str) -> None:
    with tempfile.TemporaryDirectory() as directory:
        context = Path(directory) / "context.tar.gz"
        pack_context(context)
        size = context.stat().st_size
        build = call(
            client,
            "POST",
            "/template-builds",
            json={
                "name": name,
                "size_bytes": size,
                "description": "Agno sandbox runtime",
            },
        )
        print(f"Uploading {size / 1e6:.1f} MB of build context for {build['id']}")
        with context.open("rb") as stream:
            # The upload URL is its own credential, so the API key is not sent to it.
            uploaded = httpx.put(
                build["upload_url"], content=stream.read(), timeout=600
            )
        if uploaded.status_code >= 300:
            raise SystemExit(
                f"Upload failed: {uploaded.status_code} {uploaded.text[:500]}"
            )
    call(client, "POST", f"/template-builds/{build['id']}/start")
    offset = 0
    while True:
        status = call(
            client,
            "GET",
            f"/template-builds/{build['id']}/logs",
            params={"offset": offset},
        )
        if status.get("data"):
            print(status["data"], end="", flush=True)
        offset = status.get("offset", offset)
        if status["status"] == "succeeded":
            break
        if status["status"] == "failed":
            raise SystemExit(f"Build failed: {status.get('error')}")
        time.sleep(5)
    template = call(
        client, "PATCH", f"/templates/{name}", json={"entrypoint": ENTRYPOINT}
    )
    print(f"Template {template['name']} is at revision {template.get('revision')}.")
    print(f"export AGENT37_TEMPLATE={template['name']}")


def teardown(client: httpx.Client, name: str) -> None:
    response = client.delete(f"{API}/templates/{name}")
    if response.status_code not in (200, 404):
        raise SystemExit(
            f"Agent 37 refused the delete: {response.status_code} {response.text[:1000]}"
        )
    print(
        f"Template {name} "
        + ("removed." if response.status_code == 200 else "does not exist.")
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("action", choices=("deploy", "teardown"))
    parser.add_argument("--name", default="agno-sandbox")
    args = parser.parse_args()
    headers = {"Authorization": "Bearer " + os.environ["AGENT37_API_KEY"]}
    with httpx.Client(headers=headers, timeout=120) as client:
        if args.action == "deploy":
            deploy(client, args.name)
        else:
            teardown(client, args.name)


if __name__ == "__main__":
    main()
