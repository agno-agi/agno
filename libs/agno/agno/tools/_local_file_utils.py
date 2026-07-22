"""Shared helpers for local filesystem-oriented tools."""

from __future__ import annotations

import unicodedata
from fnmatch import fnmatch, fnmatchcase
from pathlib import Path
from typing import Sequence

DEFAULT_EXCLUDE_PATTERNS = [
    # Agent and local scratch state
    ".context",
    ".conductor",
    ".claude",
    ".codex",
    ".cursor",
    # Environments and secrets
    ".venv",
    ".venvs",
    "venv",
    ".env*",
    "*.env",
    # Version control
    ".git",
    ".hg",
    ".svn",
    # Python caches and build artifacts
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".tox",
    ".nox",
    ".ipynb_checkpoints",
    "dist",
    "build",
    "*.egg-info",
    # JavaScript and TypeScript
    "node_modules",
    ".next",
    ".turbo",
    ".nuxt",
    ".svelte-kit",
    ".docusaurus",
    ".parcel-cache",
    ".nyc_output",
    "*.tsbuildinfo",
    ".serverless",
    # JVM (Java, Kotlin, Android, Gradle)
    ".gradle",
    ".kotlin",
    "*.class",
    # Dart and Flutter
    ".dart_tool",
    ".flutter-plugins",
    ".flutter-plugins-dependencies",
    # Swift and Xcode
    ".build",
    "xcuserdata",
    "*.xcuserstate",
    # Ruby
    ".bundle",
    "*.gem",
    ".yardoc",
    # Elixir
    "_build",
    ".elixir_ls",
    # .NET / Visual Studio
    ".vs",
    # Infrastructure as Code
    ".terraform",
    "*.tfstate",
    "*.tfstate.*",
    ".terragrunt-cache",
    # OS artifacts
    ".DS_Store",
]


def _fold(text: str) -> str:
    """Normalize to NFC and casefold so case and unicode-normalization variants compare equal."""
    return unicodedata.normalize("NFC", text).casefold()


def path_matches_exclude(path: Path, root: Path, exclude_patterns: Sequence[str], casefold: bool = False) -> bool:
    """Return True when any path component matches an exclude pattern.

    With ``casefold=True``, components and patterns are NFC-normalized and
    casefolded before matching, so ``.ENV`` matches ``.env*`` and NFD spellings
    match their NFC patterns. Meant for enforcement guards: case-insensitive
    filesystems (macOS, Windows) would otherwise let case variants reach an
    excluded file. On case-sensitive filesystems this over-blocks case-variant
    names by design.
    """
    if not exclude_patterns:
        return False
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    if casefold:
        return any(fnmatchcase(_fold(part), _fold(pattern)) for part in rel.parts for pattern in exclude_patterns)
    return any(fnmatch(part, pattern) for part in rel.parts for pattern in exclude_patterns)
