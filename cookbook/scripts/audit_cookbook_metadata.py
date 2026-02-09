#!/usr/bin/env python3
"""Audit cookbook folders for required metadata files.

Checks cookbook folders that contain runnable Python examples and verifies:
- README.md
- TEST_LOG.md

Usage examples:
  python3 cookbook/scripts/audit_cookbook_metadata.py
  python3 cookbook/scripts/audit_cookbook_metadata.py --scope recursive --fail-on-missing
  python3 cookbook/scripts/audit_cookbook_metadata.py --output-format json --write-json .context/cookbook-metadata.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

REQUIRED_FILES = ("README.md", "TEST_LOG.md")
SKIP_DIR_NAMES = {"__pycache__", ".git", ".context"}
SKIP_PATH_PREFIXES = {"scripts"}


@dataclass
class FolderAudit:
    path: str
    has_readme: bool
    has_test_log: bool
    missing_files: list[str]


def is_example_python_file(path: Path) -> bool:
    return path.is_file() and path.suffix == ".py" and path.name != "__init__.py"


def should_skip(path: Path, base_dir: Path) -> bool:
    rel_parts = path.relative_to(base_dir).parts
    if any(part in SKIP_DIR_NAMES for part in rel_parts):
        return True
    if rel_parts and rel_parts[0] in SKIP_PATH_PREFIXES:
        return True
    return False


def has_examples(path: Path, scope: str) -> bool:
    if scope == "direct":
        return any(is_example_python_file(child) for child in path.iterdir())
    if scope == "recursive":
        return any(is_example_python_file(child) for child in path.rglob("*.py"))
    raise ValueError(f"Unsupported scope: {scope}")


def iter_candidate_dirs(base_dir: Path) -> Iterable[Path]:
    for root, dirnames, _ in os.walk(base_dir):
        path = Path(root)
        if should_skip(path, base_dir):
            dirnames[:] = []
            continue
        dirnames[:] = [
            d
            for d in dirnames
            if d not in SKIP_DIR_NAMES and not should_skip(path / d, base_dir)
        ]
        yield path


def audit(base_dir: Path, scope: str) -> list[FolderAudit]:
    audits: list[FolderAudit] = []
    for folder in iter_candidate_dirs(base_dir):
        if folder == base_dir:
            continue
        if not has_examples(folder, scope=scope):
            continue
        has_readme = (folder / "README.md").exists()
        has_test_log = (folder / "TEST_LOG.md").exists()
        missing = [name for name in REQUIRED_FILES if not (folder / name).exists()]
        audits.append(
            FolderAudit(
                path=folder.as_posix(),
                has_readme=has_readme,
                has_test_log=has_test_log,
                missing_files=missing,
            )
        )
    audits.sort(key=lambda row: row.path)
    return audits


def build_summary(rows: list[FolderAudit]) -> dict[str, int]:
    total = len(rows)
    missing_any = sum(1 for row in rows if row.missing_files)
    missing_readme = sum(1 for row in rows if not row.has_readme)
    missing_test_log = sum(1 for row in rows if not row.has_test_log)
    compliant = total - missing_any
    return {
        "total_folders": total,
        "compliant_folders": compliant,
        "missing_any": missing_any,
        "missing_readme": missing_readme,
        "missing_test_log": missing_test_log,
    }


def render_text(
    rows: list[FolderAudit], summary: dict[str, int], base_dir: Path
) -> str:
    lines: list[str] = []
    lines.append(f"Cookbook metadata audit for {base_dir.as_posix()}")
    lines.append("")
    lines.append(
        "Summary: "
        f"total={summary['total_folders']} "
        f"compliant={summary['compliant_folders']} "
        f"missing_any={summary['missing_any']} "
        f"missing_readme={summary['missing_readme']} "
        f"missing_test_log={summary['missing_test_log']}"
    )
    lines.append("")
    lines.append("Folder results:")
    for row in rows:
        status = (
            "OK" if not row.missing_files else "MISSING " + ",".join(row.missing_files)
        )
        lines.append(f"- [{status}] {row.path}")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-dir",
        default="cookbook",
        help="Directory to audit (default: cookbook).",
    )
    parser.add_argument(
        "--scope",
        choices=["direct", "recursive"],
        default="direct",
        help="direct: folder has .py files directly. recursive: folder has .py files in any descendants.",
    )
    parser.add_argument(
        "--min-depth",
        type=int,
        default=1,
        help="Minimum folder depth under base-dir to include (default: 1).",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=2,
        help="Maximum folder depth under base-dir to include (default: 2). Use -1 for no limit.",
    )
    parser.add_argument(
        "--output-format",
        choices=["text", "json"],
        default="text",
        help="Render output as plain text or JSON (default: text).",
    )
    parser.add_argument(
        "--write-json",
        default=None,
        help="Optional path to write JSON output.",
    )
    parser.add_argument(
        "--fail-on-missing",
        action="store_true",
        help="Exit 1 when any folder is missing required files.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_dir = Path(args.base_dir).resolve()
    if args.min_depth < 1:
        print("Error: --min-depth must be >= 1", file=sys.stderr)
        return 2
    if args.max_depth != -1 and args.max_depth < args.min_depth:
        print(
            "Error: --max-depth must be >= --min-depth, or -1",
            file=sys.stderr,
        )
        return 2

    raw_rows = audit(base_dir=base_dir, scope=args.scope)
    rows: list[FolderAudit] = []
    for row in raw_rows:
        folder = Path(row.path)
        depth = len(folder.relative_to(base_dir).parts)
        if depth < args.min_depth:
            continue
        if args.max_depth != -1 and depth > args.max_depth:
            continue
        rows.append(row)
    summary = build_summary(rows)

    payload = {
        "base_dir": base_dir.as_posix(),
        "scope": args.scope,
        "min_depth": args.min_depth,
        "max_depth": args.max_depth,
        "required_files": list(REQUIRED_FILES),
        "summary": summary,
        "folders": [asdict(row) for row in rows],
    }

    if args.output_format == "json":
        print(json.dumps(payload, indent=2))
    else:
        print(render_text(rows, summary=summary, base_dir=base_dir))

    if args.write_json:
        output_path = Path(args.write_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if args.fail_on_missing and summary["missing_any"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
