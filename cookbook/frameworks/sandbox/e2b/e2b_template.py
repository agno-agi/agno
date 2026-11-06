"""Build the E2B template that E2BSandbox runs. This uses E2B build minutes.

Set E2B_API_KEY, then:

    .venv/bin/python cookbook/frameworks/sandbox/e2b/e2b_template.py --name agno-sandbox

The template installs the same packages as the Docker image in ../Dockerfile, from this
checkout's public package sources only. It makes /workspace and /runtime private to E2B's
unprivileged `user`, with /runtime as its home, and creates the root-only directory
checkpoints pass through. E2B gives `user` passwordless sudo after these steps, so
E2BSandbox strips every setuid bit when it creates a computer.
"""

import argparse
import shutil
import tempfile
from pathlib import Path

from e2b import Template, default_build_logger

# Keep these in step with ../Dockerfile.
BASE_IMAGE = "python:3.12-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f"
PACKAGES = '"/opt/agno[claude,codex]" sqlalchemy==2.0.52 claude-agent-sdk==0.2.165 openai-codex==0.162.1'

SETUP = " && ".join(
    [
        "(id -u user >/dev/null 2>&1 || useradd --uid 1000 --create-home user)",
        "mkdir -p /workspace /runtime",
        "chown user:user /workspace /runtime",
        "chmod 700 /workspace /runtime",
        "usermod --home /runtime user",
        "install -d -m 700 -o root -g root /var/lib/agno-sandbox",
    ]
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="agno-sandbox")
    parser.add_argument("--cpus", type=int, default=2)
    parser.add_argument("--memory-mb", type=int, default=4096)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[4]
    with tempfile.TemporaryDirectory(prefix="agno-e2b-build-") as directory:
        context = Path(directory)
        shutil.copytree(
            root / "libs/agno/agno",
            context / "agno",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        for filename in ("pyproject.toml", "LICENSE"):
            shutil.copyfile(root / "libs/agno" / filename, context / filename)
        shutil.copyfile(root / "README.md", context / "README.md")
        template = (
            Template(file_context_path=str(context))
            .from_image(BASE_IMAGE)
            .set_user("root")
            .run_cmd(
                "sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources"
                " && apt-get update && apt-get install -y --no-install-recommends git ca-certificates"
                " && rm -rf /var/lib/apt/lists/*"
            )
            .copy("agno", "/opt/agno/agno")
            .copy(["pyproject.toml", "LICENSE", "README.md"], "/opt/agno/")
            .run_cmd(
                f"pip install --no-cache-dir {PACKAGES}"
                ' && python -c "import agno.sandbox.runtime, claude_agent_sdk, openai_codex"'
            )
            .run_cmd(SETUP)
            .set_workdir("/workspace")
            .set_user("user")
        )
        info = Template.build(
            template,
            args.name,
            cpu_count=args.cpus,
            memory_mb=args.memory_mb,
            on_build_logs=default_build_logger(),
        )
    print(f"Built E2B template {args.name} ({info.template_id})")


if __name__ == "__main__":
    main()
