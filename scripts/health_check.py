#!/usr/bin/env python3
"""
Intelligent test selector for Agno.

Analyzes git diffs to determine which integration tests are affected by code changes,
then runs only those tests. Saves time by skipping unrelated test suites.

Usage:
    # Run affected tests against main branch
    python scripts/health_test.py

    # Run against a specific base branch/commit
    python scripts/health_test.py --base origin/release/2.5

    # Dry run - just show what would be run
    python scripts/health_test.py --dry-run

    # Show verbose diff analysis
    python scripts/health_test.py --verbose

    # Output affected test categories as JSON (for CI matrix)
    python scripts/health_test.py --output-json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Terminal colors
# ---------------------------------------------------------------------------

ORANGE = "\033[38;5;208m"
GREEN = "\033[38;5;82m"
RED = "\033[38;5;196m"
CYAN = "\033[38;5;117m"
DIM = "\033[2m"
BOLD = "\033[1m"
NC = "\033[0m"

BANNER = r"""
     █████╗  ██████╗ ███╗   ██╗ ██████╗
    ██╔══██╗██╔════╝ ████╗  ██║██╔═══██╗
    ███████║██║  ███╗██╔██╗ ██║██║   ██║
    ██╔══██║██║   ██║██║╚██╗██║██║   ██║
    ██║  ██║╚██████╔╝██║ ╚████║╚██████╔╝
    ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝
"""


def print_banner() -> None:
    print(f"{ORANGE}{BANNER}{NC}")
    print(f"    {DIM}Affected Test Runner{NC}")
    print()


def print_heading(text: str) -> None:
    print(f"    {BOLD}{text}{NC}")


def print_info(text: str) -> None:
    print(f"    {DIM}{text}{NC}")


def print_success(text: str) -> None:
    print(f"    {GREEN}{text}{NC}")


def print_error(text: str) -> None:
    print(f"    {RED}{text}{NC}")


def print_category(name: str, description: str) -> None:
    print(f"    {CYAN}{name:<25}{NC} {DIM}{description}{NC}")


def print_file(path: str) -> None:
    print(f"      {DIM}{path}{NC}")


def print_separator() -> None:
    print(f"    {DIM}{'─' * 50}{NC}")


# ---------------------------------------------------------------------------
# Config: mapping from source paths to integration test paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
INTEGRATION_TEST_ROOT = REPO_ROOT / "libs" / "agno" / "tests" / "integration"
SRC_ROOT = "libs/agno/agno"
TEST_PREFIX = "libs/agno/tests/integration"


@dataclass
class TestCategory:
    """A category of integration tests that can be triggered by source changes."""

    name: str
    test_paths: list[str]
    description: str = ""
    # Source path prefixes that trigger this category
    source_triggers: list[str] = field(default_factory=list)
    # If True, this category is triggered when "core" code changes
    triggered_by_core: bool = False


# Model providers - each gets its own category so we only run the affected provider
MODEL_PROVIDERS = [
    "aimlapi", "anthropic", "aws", "azure", "cerebras", "cohere", "cometapi",
    "dashscope", "deepinfra", "deepseek", "fireworks", "google", "groq",
    "huggingface", "ibm", "langdb", "litellm", "litellm_openai", "lmstudio",
    "meta", "mistral", "nebius", "nvidia", "ollama", "openai", "openrouter",
    "perplexity", "portkey", "sambanova", "together", "vercel", "vertexai",
    "vllm", "xai",
]

# Build model categories dynamically
MODEL_CATEGORIES = [
    TestCategory(
        name=f"models/{provider}",
        test_paths=[f"{TEST_PREFIX}/models/{provider}"],
        description=f"{provider} model tests",
        source_triggers=[f"{SRC_ROOT}/models/{provider}/"],
    )
    for provider in MODEL_PROVIDERS
]

# Core categories - mapped from source dirs to test dirs
CORE_CATEGORIES = [
    TestCategory(
        name="agent",
        test_paths=[f"{TEST_PREFIX}/agent"],
        description="Agent integration tests",
        source_triggers=[
            f"{SRC_ROOT}/agent/",
            f"{SRC_ROOT}/run/",
            f"{SRC_ROOT}/reasoning/",
            f"{SRC_ROOT}/guardrails/",
            f"{SRC_ROOT}/approval/",
            f"{SRC_ROOT}/hooks/",
        ],
        triggered_by_core=True,
    ),
    TestCategory(
        name="teams",
        test_paths=[f"{TEST_PREFIX}/teams"],
        description="Team integration tests",
        source_triggers=[
            f"{SRC_ROOT}/team/",
        ],
        triggered_by_core=True,
    ),
    TestCategory(
        name="workflows",
        test_paths=[f"{TEST_PREFIX}/workflows"],
        description="Workflow integration tests",
        source_triggers=[
            f"{SRC_ROOT}/workflow/",
        ],
        triggered_by_core=True,
    ),
    TestCategory(
        name="db",
        test_paths=[f"{TEST_PREFIX}/db"],
        description="Database adapter tests",
        source_triggers=[
            f"{SRC_ROOT}/db/",
        ],
    ),
    TestCategory(
        name="knowledge",
        test_paths=[f"{TEST_PREFIX}/knowledge"],
        description="Knowledge/RAG tests",
        source_triggers=[
            f"{SRC_ROOT}/knowledge/",
            f"{SRC_ROOT}/document/",
        ],
    ),
    TestCategory(
        name="embedder",
        test_paths=[f"{TEST_PREFIX}/embedder"],
        description="Embedder tests",
        source_triggers=[
            f"{SRC_ROOT}/embedder/",
        ],
    ),
    TestCategory(
        name="tools",
        test_paths=[f"{TEST_PREFIX}/tools"],
        description="Tool integration tests",
        source_triggers=[
            f"{SRC_ROOT}/tools/",
        ],
    ),
    TestCategory(
        name="vectordb",
        test_paths=[f"{TEST_PREFIX}/vector_dbs"],
        description="Vector database tests",
        source_triggers=[
            f"{SRC_ROOT}/vectordb/",
        ],
    ),
    TestCategory(
        name="memory",
        test_paths=[f"{TEST_PREFIX}/managers", f"{TEST_PREFIX}/session"],
        description="Memory and session manager tests",
        source_triggers=[
            f"{SRC_ROOT}/memory/",
        ],
        triggered_by_core=True,
    ),
    TestCategory(
        name="os",
        test_paths=[f"{TEST_PREFIX}/os"],
        description="AgentOS tests",
        source_triggers=[
            f"{SRC_ROOT}/os/",
            f"{SRC_ROOT}/api/",
            f"{SRC_ROOT}/app/",
            f"{SRC_ROOT}/playground/",
        ],
    ),
    TestCategory(
        name="reranker",
        test_paths=[f"{TEST_PREFIX}/reranker"],
        description="Reranker tests",
        source_triggers=[
            f"{SRC_ROOT}/reranker/",
        ],
    ),
]

ALL_CATEGORIES = CORE_CATEGORIES + MODEL_CATEGORIES

# Files that, when changed, should trigger ALL core tests (agent, teams, workflows, memory)
# These are foundational modules used across the framework
CORE_TRIGGER_PATHS = [
    f"{SRC_ROOT}/run/",
    f"{SRC_ROOT}/models/base.py",
    f"{SRC_ROOT}/models/message.py",
    f"{SRC_ROOT}/models/response.py",
    f"{SRC_ROOT}/models/defaults.py",
    f"{SRC_ROOT}/models/utils.py",
    f"{SRC_ROOT}/media.py",
    f"{SRC_ROOT}/compression/",
]


def get_changed_files(base: str) -> list[str]:
    """Get list of files changed compared to the base ref."""
    # First try diff against the base
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", base],
            capture_output=True,
            text=True,
            check=True,
            cwd=REPO_ROOT,
        )
        files = [f for f in result.stdout.strip().splitlines() if f]
    except subprocess.CalledProcessError:
        # If the base ref doesn't exist, try merge-base
        try:
            merge_base = subprocess.run(
                ["git", "merge-base", "HEAD", base],
                capture_output=True,
                text=True,
                check=True,
                cwd=REPO_ROOT,
            )
            base_commit = merge_base.stdout.strip()
            result = subprocess.run(
                ["git", "diff", "--name-only", base_commit],
                capture_output=True,
                text=True,
                check=True,
                cwd=REPO_ROOT,
            )
            files = [f for f in result.stdout.strip().splitlines() if f]
        except subprocess.CalledProcessError:
            print_error(f"Could not determine diff against '{base}'")
            print_info("Make sure the base branch/commit exists and is fetched.")
            sys.exit(1)

    # Also include untracked and staged files
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
            cwd=REPO_ROOT,
        )
        for line in status.stdout.strip().splitlines():
            if not line:
                continue
            # Porcelain format: "XY filename" or "XY old -> new"
            # X=index status, Y=worktree status, then space, then path.
            # Use regex to reliably extract the filename regardless of
            # status char combinations (M, A, D, R, C, U, ?, !, space).
            m = re.match(r"^[MADRCU?! ]{1,2}\s+(.+)$", line)
            if not m:
                continue
            raw = m.group(1)
            # Handle renames: "old -> new"
            if " -> " in raw:
                raw = raw.split(" -> ")[-1]
            if raw and raw not in files:
                files.append(raw)
    except subprocess.CalledProcessError:
        pass

    return files


def is_core_change(changed_files: list[str]) -> bool:
    """Check if any changed file is a core module that affects many test categories."""
    for f in changed_files:
        for trigger in CORE_TRIGGER_PATHS:
            if f.startswith(trigger) or f == trigger.rstrip("/"):
                return True
    return False


def determine_affected_categories(changed_files: list[str]) -> list[TestCategory]:
    """Map changed files to affected test categories."""
    affected: dict[str, TestCategory] = {}
    core_changed = is_core_change(changed_files)

    # If models/base.py or similar core model files changed, run all model tests
    model_base_changed = any(
        f.startswith(f"{SRC_ROOT}/models/") and not any(f.startswith(f"{SRC_ROOT}/models/{p}/") for p in MODEL_PROVIDERS)
        for f in changed_files
    )

    for category in ALL_CATEGORIES:
        # Check if any source trigger matches
        for changed_file in changed_files:
            for trigger in category.source_triggers:
                if changed_file.startswith(trigger) or changed_file == trigger.rstrip("/"):
                    affected[category.name] = category
                    break

        # If core code changed, trigger categories marked as triggered_by_core
        if core_changed and category.triggered_by_core:
            affected[category.name] = category

        # If model base files changed, trigger all model categories
        if model_base_changed and category.name.startswith("models/"):
            affected[category.name] = category

    # If integration test files themselves changed, include those categories
    for changed_file in changed_files:
        if changed_file.startswith(TEST_PREFIX):
            # Find which category this test belongs to
            for category in ALL_CATEGORIES:
                for test_path in category.test_paths:
                    if changed_file.startswith(test_path):
                        affected[category.name] = category
                        break

    return sorted(affected.values(), key=lambda c: c.name)


def filter_existing_paths(categories: list[TestCategory]) -> list[TestCategory]:
    """Filter out test paths that don't actually exist on disk."""
    filtered = []
    for cat in categories:
        existing = [p for p in cat.test_paths if (REPO_ROOT / p).exists()]
        if existing:
            filtered.append(TestCategory(
                name=cat.name,
                test_paths=existing,
                description=cat.description,
                source_triggers=cat.source_triggers,
                triggered_by_core=cat.triggered_by_core,
            ))
    return filtered


def run_tests(categories: list[TestCategory], pytest_args: list[str]) -> int:
    """Run pytest for the affected test categories. Returns exit code."""
    test_paths = []
    for cat in categories:
        test_paths.extend(cat.test_paths)

    if not test_paths:
        print_info("No test paths to run.")
        return 0

    cmd = [
        sys.executable, "-m", "pytest",
        *test_paths,
        "-v",
        *pytest_args,
    ]

    env = os.environ.copy()
    env["AGNO_TELEMETRY"] = "false"

    print()
    print_separator()
    print_heading("Running pytest")
    print_info(f"> {' '.join(cmd)}")
    print_separator()
    print()

    result = subprocess.run(cmd, cwd=REPO_ROOT, env=env)
    return result.returncode


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run integration tests affected by your code changes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--base",
        default="origin/main",
        help="Base branch or commit to diff against (default: origin/main)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be run without running tests",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed diff analysis",
    )
    parser.add_argument(
        "--output-json",
        action="store_true",
        help="Output affected categories as JSON (for CI matrix generation)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all integration tests (ignore diff analysis)",
    )
    parser.add_argument(
        "pytest_args",
        nargs="*",
        help="Additional arguments to pass to pytest (after --)",
    )

    args = parser.parse_args()

    # Skip banner for JSON output
    if not args.output_json:
        print_banner()

    # Get changed files
    if args.all:
        categories = filter_existing_paths(ALL_CATEGORIES)
        changed_files = []
        if not args.output_json:
            print_heading("Mode: Run all integration tests")
            print()
    else:
        if not args.output_json:
            print_heading(f"Analyzing diff against {args.base}...")
            print()

        changed_files = get_changed_files(args.base)

        if not changed_files:
            print_success(f"No changes detected against '{args.base}'. Nothing to test.")
            print()
            sys.exit(0)

        if args.verbose and not args.output_json:
            print_info(f"Changed files ({len(changed_files)}):")
            for f in sorted(changed_files):
                print_file(f)
            print()

        categories = determine_affected_categories(changed_files)
        categories = filter_existing_paths(categories)

    if not categories:
        print_success("No integration tests affected by the changes.")
        if args.verbose and changed_files:
            non_src = [f for f in changed_files if not f.startswith(SRC_ROOT)]
            if non_src:
                print()
                print_info("Changed files outside source tree (no tests triggered):")
                for f in non_src:
                    print_file(f)
        print()
        sys.exit(0)

    # JSON output for CI (skip all formatting)
    if args.output_json:
        output = {
            "categories": [
                {
                    "name": cat.name,
                    "test_paths": cat.test_paths,
                    "description": cat.description,
                }
                for cat in categories
            ]
        }
        print(json.dumps(output, indent=2))
        sys.exit(0)

    # Output summary
    total_paths = sum(len(c.test_paths) for c in categories)
    print_heading(f"Affected test suites ({len(categories)} suites, {total_paths} test paths)")
    print()
    for cat in categories:
        print_category(cat.name, cat.description)
        if args.verbose:
            for tp in cat.test_paths:
                print_file(tp)
    print()

    # Dry run
    if args.dry_run:
        print_separator()
        all_paths = []
        for cat in categories:
            all_paths.extend(cat.test_paths)
        print_info("Dry run -- no tests executed.")
        print()
        print_info(f"> pytest {' '.join(all_paths)} -v")
        print()
        sys.exit(0)

    # Run tests
    exit_code = run_tests(categories, args.pytest_args)

    # Final status
    print()
    print_separator()
    if exit_code == 0:
        print_success("All affected tests passed.")
    else:
        print_error("Some tests failed.")
    print_separator()
    print()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
