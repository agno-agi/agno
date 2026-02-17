#!/usr/bin/env python3
"""Validate cookbook Python example structure.

This checker enforces a lightweight, teachable pattern for runnable cookbook
examples:
1. Module docstring at top.
2. Sectioned layout using banner comments.
3. A "Create ..." section and a "Run ..." section, in that order.
4. Main execution gate: if __name__ == "__main__":.
5. No emoji characters in Python source.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF]")
MAIN_GATE_RE = re.compile(r'if __name__ == ["\']__main__["\']:')
SECTION_RE = re.compile(r"^# [-=]+\n# (?P<title>.+?)\n# [-=]+$", re.MULTILINE)
SKIP_FILE_NAMES = {"__init__.py"}
SKIP_DIR_NAMES = {"__pycache__", ".git", ".context"}


@dataclass
class Violation:
    path: str
    line: int
    code: str
    message: str


def iter_python_files(base_dir: Path, recursive: bool) -> list[Path]:
    pattern = "**/*.py" if recursive else "*.py"
    files: list[Path] = []
    for path in sorted(base_dir.glob(pattern)):
        if not path.is_file():
            continue
        if path.name in SKIP_FILE_NAMES:
            continue
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        files.append(path)
    return files


def find_sections(text: str) -> list[tuple[str, int]]:
    sections: list[tuple[str, int]] = []
    for match in SECTION_RE.finditer(text):
        title = match.group("title").strip()
        # 1-based line number of the section title line
        line = text[: match.start()].count("\n") + 2
        sections.append((title, line))
    return sections


def find_first_section_line(
    sections: list[tuple[str, int]], keyword: str
) -> int | None:
    needle = re.compile(rf"\b{re.escape(keyword)}\b", re.IGNORECASE)
    for title, line in sections:
        if needle.search(title):
            return line
    return None


def validate_file(path: Path) -> list[Violation]:
    violations: list[Violation] = []
    text = path.read_text(encoding="utf-8")

    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        violations.append(
            Violation(
                path=path.as_posix(),
                line=exc.lineno or 1,
                code="syntax_error",
                message=exc.msg,
            )
        )
        return violations

    if not ast.get_docstring(tree, clean=False):
        violations.append(
            Violation(
                path=path.as_posix(),
                line=1,
                code="missing_docstring",
                message="Module docstring is required.",
            )
        )

    if not MAIN_GATE_RE.search(text):
        violations.append(
            Violation(
                path=path.as_posix(),
                line=1,
                code="missing_main_gate",
                message='Missing `if __name__ == "__main__":` execution gate.',
            )
        )

    sections = find_sections(text)
    if not sections:
        violations.append(
            Violation(
                path=path.as_posix(),
                line=1,
                code="missing_sections",
                message="Expected section banners (# --- or # === style).",
            )
        )
    else:
        create_line = find_first_section_line(sections=sections, keyword="create")
        run_line = find_first_section_line(sections=sections, keyword="run")

        if create_line is None:
            violations.append(
                Violation(
                    path=path.as_posix(),
                    line=1,
                    code="missing_create_section",
                    message='Missing section title containing the word "Create".',
                )
            )
        if run_line is None:
            violations.append(
                Violation(
                    path=path.as_posix(),
                    line=1,
                    code="missing_run_section",
                    message='Missing section title containing the word "Run".',
                )
            )
        if create_line is not None and run_line is not None and create_line > run_line:
            violations.append(
                Violation(
                    path=path.as_posix(),
                    line=create_line,
                    code="section_order",
                    message='"Create ..." section must appear before "Run ..." section.',
                )
            )

    for match in EMOJI_RE.finditer(text):
        line = text[: match.start()].count("\n") + 1
        violations.append(
            Violation(
                path=path.as_posix(),
                line=line,
                code="emoji_not_allowed",
                message="Emoji characters are not allowed in cookbook Python files.",
            )
        )

    return violations


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-dir",
        default="cookbook/00_quickstart",
        help="Base directory containing cookbook python examples.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Scan python files recursively under base-dir.",
    )
    parser.add_argument(
        "--output-format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_dir = Path(args.base_dir).resolve()
    files = iter_python_files(base_dir=base_dir, recursive=args.recursive)

    violations: list[Violation] = []
    for path in files:
        violations.extend(validate_file(path))

    payload = {
        "base_dir": base_dir.as_posix(),
        "checked_files": len(files),
        "violation_count": len(violations),
        "violations": [asdict(v) for v in violations],
    }

    if args.output_format == "json":
        print(json.dumps(payload, indent=2))
    else:
        print(
            f"Checked {payload['checked_files']} file(s) in {payload['base_dir']}. "
            f"Violations: {payload['violation_count']}"
        )
        for v in violations:
            print(f"{v.path}:{v.line} [{v.code}] {v.message}")

    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
