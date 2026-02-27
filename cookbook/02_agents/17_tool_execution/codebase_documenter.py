"""
Tool Execution — Codebase Documenter (Multi-MCP, 25 tools)
============================================================
Uses tool execution with two MCP servers (Filesystem + Git) to automatically
document a Python project. The agent reads source files, generates a
README.md, writes it to disk, and commits it — all orchestrated through
tool execution's single-program execution.

Combined: 25 tools (13 filesystem + 12 git), triggering discovery mode.
The agent uses search_tools to find relevant functions across both servers,
then writes one Python program that pipelines: read -> analyze -> write -> commit.

Requirements:
  - Node.js (npx) for the filesystem MCP server
  - uv (uvx) for the git MCP server

Run:
  .venvs/demo/bin/python cookbook/02_agents/17_tool_execution/codebase_documenter.py
"""

import asyncio
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.mcp import MCPTools

# A small Python project with no documentation — the agent's job is to fix that
SAMPLE_FILES = {
    "mathkit/__init__.py": (
        "from mathkit.stats import mean, median, stdev\n"
        "from mathkit.convert import celsius_to_fahrenheit, kg_to_lbs\n"
        "from mathkit.validate import is_positive, is_in_range, is_numeric_list\n"
    ),
    "mathkit/stats.py": (
        "def mean(values):\n"
        "    if not values:\n"
        "        raise ValueError('Empty sequence')\n"
        "    return sum(values) / len(values)\n"
        "\n"
        "\n"
        "def median(values):\n"
        "    if not values:\n"
        "        raise ValueError('Empty sequence')\n"
        "    s = sorted(values)\n"
        "    n = len(s)\n"
        "    if n % 2 == 1:\n"
        "        return s[n // 2]\n"
        "    return (s[n // 2 - 1] + s[n // 2]) / 2\n"
        "\n"
        "\n"
        "def stdev(values):\n"
        "    if len(values) < 2:\n"
        "        raise ValueError('Need at least 2 values')\n"
        "    avg = mean(values)\n"
        "    variance = sum((x - avg) ** 2 for x in values) / (len(values) - 1)\n"
        "    return variance ** 0.5\n"
    ),
    "mathkit/convert.py": (
        "def celsius_to_fahrenheit(c):\n"
        "    return c * 9 / 5 + 32\n"
        "\n"
        "\n"
        "def fahrenheit_to_celsius(f):\n"
        "    return (f - 32) * 5 / 9\n"
        "\n"
        "\n"
        "def kg_to_lbs(kg):\n"
        "    return kg * 2.20462\n"
        "\n"
        "\n"
        "def lbs_to_kg(lbs):\n"
        "    return lbs / 2.20462\n"
        "\n"
        "\n"
        "def meters_to_feet(m):\n"
        "    return m * 3.28084\n"
        "\n"
        "\n"
        "def feet_to_meters(ft):\n"
        "    return ft / 3.28084\n"
    ),
    "mathkit/validate.py": (
        "def is_positive(value):\n"
        "    return isinstance(value, (int, float)) and value > 0\n"
        "\n"
        "\n"
        "def is_in_range(value, low, high):\n"
        "    return low <= value <= high\n"
        "\n"
        "\n"
        "def is_numeric_list(values):\n"
        "    return isinstance(values, (list, tuple)) and all(\n"
        "        isinstance(v, (int, float)) for v in values\n"
        "    )\n"
    ),
}

TASK_TEMPLATE = (
    "Document the Python project at {project_dir}.\n\n"
    "1. Read the source files:\n"
    "   - list_directory(path='{project_dir}/mathkit') to see what files exist\n"
    "   - read_text_file(path='{project_dir}/mathkit/__init__.py')\n"
    "   - read_text_file(path='{project_dir}/mathkit/stats.py')\n"
    "   - read_text_file(path='{project_dir}/mathkit/convert.py')\n"
    "   - read_text_file(path='{project_dir}/mathkit/validate.py')\n"
    "2. Analyze ALL the code you read — every module, function, parameter\n"
    "3. Generate a comprehensive README.md covering all modules and functions with examples\n"
    "4. write_file(path='{project_dir}/README.md', content=readme_text)\n"
    "5. git_add(repo_path='{project_dir}', files=['README.md'])\n"
    "6. git_commit(repo_path='{project_dir}', message='docs: add README.md')"
)


def setup_sample_project(project_dir: Path):
    for rel_path, content in SAMPLE_FILES.items():
        filepath = project_dir / rel_path
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content)

    subprocess.run(["git", "init"], cwd=project_dir, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=project_dir, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit: mathkit package"],
        cwd=project_dir,
        capture_output=True,
        env={
            **__import__("os").environ,
            "GIT_AUTHOR_NAME": "Demo",
            "GIT_AUTHOR_EMAIL": "demo@example.com",
            "GIT_COMMITTER_NAME": "Demo",
            "GIT_COMMITTER_EMAIL": "demo@example.com",
        },
    )


async def main():
    # .resolve() needed on macOS where /var/folders is a symlink to /private/var/folders
    project_dir = Path(tempfile.mkdtemp(prefix="tool_exec_docs_")).resolve()
    try:
        setup_sample_project(project_dir)
        print("=" * 60)
        print("CODEBASE DOCUMENTER (Filesystem + Git MCP, tool execution)")
        print(f"Project: {project_dir}")
        print("=" * 60)

        fs_cmd = f"npx -y @modelcontextprotocol/server-filesystem {project_dir}"
        git_cmd = f"uvx --python 3.12 mcp-server-git --repository {project_dir}"

        async with (
            MCPTools(fs_cmd, timeout_seconds=30) as fs_tools,
            MCPTools(git_cmd, timeout_seconds=30) as git_tools,
        ):
            fs_count = len(fs_tools.functions)
            git_count = len(git_tools.functions)
            print(f"Filesystem tools: {fs_count}")
            print(f"Git tools: {git_count}")
            print(f"Total tools: {fs_count + git_count}")

            agent = Agent(
                name="Codebase Documenter",
                model=Claude(id="claude-sonnet-4-20250514"),
                tools=[fs_tools, git_tools],
                enable_tool_execution=True,
                tool_call_limit=10,
                markdown=True,
            )

            task = TASK_TEMPLATE.format(project_dir=project_dir)
            t0 = time.time()
            response = await agent.arun(task)
            elapsed = time.time() - t0

            print(f"\n{response.content}\n")

            # Verification
            print("=" * 60)
            print("VERIFICATION")
            print("=" * 60)

            readme = project_dir / "README.md"
            if readme.exists():
                size = readme.stat().st_size
                print(f"README.md: {size:,} bytes")
            else:
                print("README.md: NOT FOUND")

            log_result = subprocess.run(
                ["git", "-C", str(project_dir), "log", "--oneline", "-5"],
                capture_output=True,
                text=True,
            )
            if log_result.stdout:
                print(f"Git log:\n{log_result.stdout.strip()}")

            m = response.metrics
            if m:
                print("-" * 50)
                print(f"Input tokens:  {m.input_tokens:,}")
                print(f"Output tokens: {m.output_tokens:,}")
                print(f"Total tokens:  {m.total_tokens:,}")
            print(f"Duration:      {elapsed:.1f}s")
            print(f"Messages:      {len(response.messages or [])}")

            has_readme = readme.exists() and readme.stat().st_size > 100
            has_commit = "docs" in (log_result.stdout or "").lower()
            print(f"\nSTATUS: {'PASS' if has_readme and has_commit else 'FAIL'}")
    finally:
        shutil.rmtree(project_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
