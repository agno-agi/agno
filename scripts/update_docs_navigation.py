"""Update the docs.json navigation to match the generated schema files.

Scans reference-api/schema/ for .mdx files and updates the
"AgentOS API Reference" section of docs.json to reflect what's on disk.

Usage:
    python scripts/update_docs_navigation.py /path/to/docs-repo

Exits with code 0 if docs.json was updated (or already in sync),
and prints a summary of added/removed pages to stderr.
"""

import json
import os
import sys
from typing import Any

# Folder name -> display name in docs.json navigation.
# Folders listed in INTERFACE_GROUPS are nested under an "Interfaces" parent.
GROUP_NAMES: dict[str, str] = {
    "core": "Core",
    "agents": "Agents",
    "teams": "Teams",
    "workflows": "Workflows",
    "sessions": "Sessions",
    "memory": "Memory",
    "traces": "Tracing",
    "evals": "Evals",
    "knowledge": "Knowledge",
    "components": "Components",
    "registry": "Registry",
    "metrics": "Metrics",
    "database": "Database migrations",
    "a2a": "A2A",
    "agui": "AGUI",
    "slack": "Slack",
    "whatsapp": "Whatsapp",
    "schedules": "Schedules",
    "approvals": "Approvals",
    "remote-content": "Remote Content",
}

INTERFACE_GROUPS = {"a2a", "agui", "slack", "whatsapp"}

# Controls the ordering of top-level groups in the API reference section.
GROUP_ORDER = [
    "core",
    "agents",
    "teams",
    "workflows",
    "sessions",
    "memory",
    "traces",
    "evals",
    "knowledge",
    "components",
    "registry",
    "metrics",
    # "Interfaces" parent inserted here
    "database",
]

INTERFACE_ORDER = ["a2a", "agui", "slack", "whatsapp"]


def scan_schema_files(schema_dir: str) -> dict[str, list[str]]:
    """Scan schema_dir and return {folder: [page_path, ...]} sorted."""
    groups: dict[str, list[str]] = {}
    for dirpath, _, filenames in os.walk(schema_dir):
        folder = os.path.relpath(dirpath, schema_dir)
        if folder == ".":
            continue
        pages = sorted(
            f"reference-api/schema/{folder}/{f[:-4]}"
            for f in filenames
            if f.endswith(".mdx")
        )
        if pages:
            groups[folder] = pages
    return groups


def build_api_reference_nav(groups: dict[str, list[str]]) -> list[Any]:
    """Build the pages list for the AgentOS API Reference group."""
    nav: list[Any] = ["reference-api/overview"]

    # Top-level groups in order
    for folder in GROUP_ORDER:
        if folder in groups:
            nav.append({"group": GROUP_NAMES.get(folder, folder.title()), "pages": groups[folder]})

    # Interfaces parent group
    interface_pages: list[Any] = []
    for folder in INTERFACE_ORDER:
        if folder in groups:
            interface_pages.append({"group": GROUP_NAMES.get(folder, folder.upper()), "pages": groups[folder]})
    # Also pick up any interface folders not in the predefined order
    for folder in sorted(groups.keys()):
        if folder in INTERFACE_GROUPS and folder not in INTERFACE_ORDER:
            interface_pages.append({"group": GROUP_NAMES.get(folder, folder.title()), "pages": groups[folder]})

    if interface_pages:
        nav.append({"group": "Interfaces", "pages": interface_pages})

    # Any new top-level groups not in GROUP_ORDER or INTERFACE_GROUPS
    for folder in sorted(groups.keys()):
        if folder not in GROUP_ORDER and folder not in INTERFACE_GROUPS:
            nav.append({"group": GROUP_NAMES.get(folder, folder.title()), "pages": groups[folder]})

    return nav


def find_api_reference_group(docs: dict) -> tuple[list, int] | None:
    """Find the 'AgentOS API Reference' group in docs.json navigation.

    It can appear either as a direct entry in tab.groups[] or nested
    inside a group's pages[].
    """
    for tab in docs.get("navigation", {}).get("tabs", []):
        groups = tab.get("groups", [])
        # Check if it's a direct group entry in the tab
        for i, group in enumerate(groups):
            if isinstance(group, dict) and group.get("group") == "AgentOS API Reference":
                return groups, i
        # Also check nested inside group pages
        for group in groups:
            pages = group.get("pages", [])
            for i, page in enumerate(pages):
                if isinstance(page, dict) and page.get("group") == "AgentOS API Reference":
                    return pages, i
    return None


def collect_all_pages(nav: list[Any]) -> set[str]:
    """Recursively collect all page strings from a navigation structure."""
    pages: set[str] = set()
    for item in nav:
        if isinstance(item, str):
            pages.add(item)
        elif isinstance(item, dict):
            pages |= collect_all_pages(item.get("pages", []))
    return pages


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python update_docs_navigation.py /path/to/docs-repo", file=sys.stderr)
        sys.exit(1)

    docs_root = sys.argv[1]
    docs_json_path = os.path.join(docs_root, "docs.json")
    schema_dir = os.path.join(docs_root, "reference-api", "schema")

    if not os.path.isfile(docs_json_path):
        print(f"docs.json not found at {docs_json_path}", file=sys.stderr)
        sys.exit(1)

    if not os.path.isdir(schema_dir):
        print(f"Schema directory not found at {schema_dir}", file=sys.stderr)
        sys.exit(1)

    with open(docs_json_path) as f:
        docs = json.load(f)

    result = find_api_reference_group(docs)
    if result is None:
        print("Could not find 'AgentOS API Reference' group in docs.json", file=sys.stderr)
        sys.exit(1)

    parent_pages, idx = result
    old_group = parent_pages[idx]
    old_pages = collect_all_pages(old_group.get("pages", []))

    groups = scan_schema_files(schema_dir)
    new_nav = build_api_reference_nav(groups)
    new_pages = collect_all_pages(new_nav)

    added = new_pages - old_pages
    removed = old_pages - new_pages

    # Update in place
    parent_pages[idx] = {"group": "AgentOS API Reference", "pages": new_nav}

    with open(docs_json_path, "w") as f:
        json.dump(docs, f, indent=2, ensure_ascii=False)
        f.write("\n")

    if added:
        print(f"Added {len(added)} pages:", file=sys.stderr)
        for p in sorted(added):
            print(f"  + {p}", file=sys.stderr)
    if removed:
        print(f"Removed {len(removed)} pages:", file=sys.stderr)
        for p in sorted(removed):
            print(f"  - {p}", file=sys.stderr)
    if not added and not removed:
        print("Navigation already in sync.", file=sys.stderr)


if __name__ == "__main__":
    main()
