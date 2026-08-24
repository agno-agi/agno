"""Workspace — read, write, edit, search, and run shell commands in a local working directory.

Destructive operations (write/edit/move/delete/shell) require human confirmation by
default, which AgentOS renders as approval prompts in the run timeline.

Quick start:

    from agno.agent import Agent
    from agno.tools.workspace import Workspace

    agent = Agent(
        model="openai:gpt-5.4",
        tools=[
            Workspace(
                ".",
                allowed=["read", "list", "search"],
                confirm=["write", "edit", "move", "delete", "shell"],
            )
        ],
    )
"""

import asyncio
import json
import os
import posixpath
import re
import subprocess
import sys
import unicodedata
from fnmatch import fnmatch
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union

from agno.exceptions import PathSecurityError
from agno.tools import Toolkit
from agno.tools._local_file_utils import DEFAULT_EXCLUDE_PATTERNS, EXEMPT_PREFIX, compile_exclude_patterns
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.utils.path_safety import safe_join_relative_path

TEXT_EXTENSIONS = {
    # Markup and data
    ".md",
    ".txt",
    ".csv",
    ".json",
    ".yaml",
    ".yml",
    ".xml",
    ".html",
    ".rst",
    ".log",
    # Config
    ".toml",
    ".cfg",
    ".ini",
    ".env",
    ".editorconfig",
    # Committed template suffixes: `.env.example` has suffix `.example`, so without
    # these search_content skips the very files the exclude exemptions make readable.
    ".example",
    ".sample",
    ".template",
    ".dist",
    # Python
    ".py",
    ".pyi",
    # JavaScript / TypeScript
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".mjs",
    ".cjs",
    # Web
    ".css",
    ".scss",
    ".less",
    ".vue",
    ".svelte",
    # Systems languages
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".cc",
    ".cxx",
    ".rs",
    ".go",
    ".zig",
    # JVM
    ".java",
    ".kt",
    ".kts",
    ".scala",
    ".groovy",
    ".gradle",
    # .NET
    ".cs",
    ".fs",
    ".csproj",
    ".fsproj",
    # Ruby / PHP / Perl
    ".rb",
    ".php",
    ".pl",
    ".pm",
    # Functional / BEAM
    ".ex",
    ".exs",
    ".erl",
    ".hs",
    ".ml",
    ".mli",
    # Other languages
    ".swift",
    ".m",
    ".r",
    ".R",
    ".lua",
    ".dart",
    ".jl",
    # Shell and scripting
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".ps1",
    # SQL and query
    ".sql",
    ".graphql",
    ".gql",
    # Infrastructure / IaC
    ".tf",
    ".hcl",
    ".dockerfile",
    # Serialization / schema
    ".proto",
    ".avsc",
    ".thrift",
    # Build / CI
    ".makefile",
    ".cmake",
    ".bazel",
    ".bzl",
}

# Strips ANSI CSI sequences (color codes, cursor moves) from terminal output.
_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences (color codes, cursor moves) from text."""
    return _ANSI_RE.sub("", text)


def _format_size(size: float) -> str:
    """Format a file size in bytes to a human-readable string."""
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{int(size)}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}GB"


def _extract_snippet(content: str, query: str, context_chars: int = 200) -> str:
    """Extract a snippet of content around the first case-insensitive match of query."""
    lower_content = content.lower()
    lower_query = query.lower()
    idx = lower_content.find(lower_query)
    if idx == -1:
        return ""
    start = max(0, idx - context_chars)
    end = min(len(content), idx + len(query) + context_chars)
    snippet = content[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(content):
        snippet = snippet + "..."
    return snippet


def _format_with_line_numbers(text: str, start_line: int = 1) -> str:
    """Prefix each line with its 1-indexed number, ``cat -n`` style.

    The numbers reflect the actual line in the source file: when reading a chunk
    starting at line 50, the first returned line is numbered 50.
    """
    lines = text.split("\n")
    # Drop the trailing empty element produced by a terminal newline.
    if lines and lines[-1] == "":
        lines = lines[:-1]
    return "\n".join(f"{i + start_line:6d}\t{line}" for i, line in enumerate(lines))


def _validate_exclude_patterns(exclude_patterns: Optional[List[str]]) -> List[str]:
    """Return ``exclude_patterns`` as a list, or the defaults when ``None``.

    Raises ``ValueError`` for a pattern containing a path separator: patterns are matched
    against single path components, so such a pattern can never match. Also raises for a
    bare ``!``, which names no pattern to exempt.
    """
    patterns = list(exclude_patterns) if exclude_patterns is not None else list(DEFAULT_EXCLUDE_PATTERNS)
    for pattern in patterns:
        if pattern == EXEMPT_PREFIX:
            raise ValueError(
                "exclude_patterns entry '!' names no pattern. A leading '!' exempts the rest of the "
                "entry from exclusion, for example '!.env.example'."
            )
        if "/" in pattern or "\\" in pattern:
            raise ValueError(
                f"exclude_patterns entry {pattern!r} contains a path separator. Patterns are matched against "
                "single path components and cannot name a path; use the component name instead."
            )
    return patterns


def _resolve_allow_paths(root: Path, allow_paths: Optional[List[str]]) -> List[Tuple[Path, Path]]:
    """Validate ``allow_paths`` for a workspace rooted at ``root``.

    Returns one ``(as_written, resolved)`` pair per entry, both absolute under ``root``.
    Raises ``TypeError`` when ``allow_paths`` is not a list, and ``ValueError`` when an entry
    is not a relative path inside ``root`` or names ``root`` itself.
    """
    if allow_paths is None:
        return []
    if not isinstance(allow_paths, (list, tuple)):
        raise TypeError(
            f"`allow_paths` must be a list of workspace-relative paths, got {type(allow_paths).__name__}: {allow_paths!r}"
        )
    pairs: List[Tuple[Path, Path]] = []
    for raw in allow_paths:
        try:
            entry = os.fspath(raw)
            resolved = safe_join_relative_path(root, entry)
        except (TypeError, PathSecurityError, OSError) as e:
            raise ValueError(f"allow_paths entry {raw!r} is not a valid path inside the workspace root: {e}")
        if resolved == root:
            raise ValueError(
                f"allow_paths entry {raw!r} names the workspace root; pass exclude_patterns=[] to disable exclusion"
            )
        pairs.append((_lexical_join(root, entry), resolved))
    return pairs


def _lexical_join(root: Path, path: str) -> Path:
    """Join ``path`` under ``root`` as written: no symlink resolution, ``.`` and ``..`` collapsed lexically."""
    normalized = posixpath.normpath(unicodedata.normalize("NFKC", path).replace("\\", "/"))
    parts = [part for part in normalized.split("/") if part not in ("", ".", "..")]
    return root.joinpath(*parts)


def _is_case_insensitive_fs(root: Path) -> bool:
    """Return True when the filesystem holding ``root`` treats names differing only by case as one entry.

    Probes a lettered entry inside ``root``, then ``root`` itself. When nothing can be probed,
    macOS and Windows are assumed case-insensitive and other platforms case-sensitive.
    """
    candidates: List[Path] = []
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                if entry.name.swapcase() != entry.name:
                    candidates.append(Path(entry.path))
                    break
    except OSError:
        pass
    if root.name.swapcase() != root.name:
        candidates.append(root)
    for candidate in candidates:
        try:
            return os.path.samefile(candidate, candidate.with_name(candidate.name.swapcase()))
        except FileNotFoundError:
            return False
        except OSError:
            continue
    return sys.platform in ("darwin", "win32")


class Workspace(Toolkit):
    """Local-machine toolkit for read/write/edit/search/shell access to a directory tree.

    All file operations are scoped to ``root`` — paths that resolve outside it are
    rejected with an error. Shell commands run with ``cwd=root``. This is a path-scoping
    boundary, not a process sandbox: the agent can still read environment variables,
    make network calls via shell tools, and use whatever the host process can use. For
    untrusted code execution, run the agent inside a real sandbox (container, VM, or
    a service like Daytona).

    Permission model — ``allowed`` and ``confirm`` are mutually exclusive
    partitions of short aliases:

    - An alias in ``allowed`` runs silently.
    - An alias in ``confirm`` requires user approval (Agno's HITL pause/resume).
    - An alias in **neither** list is not registered with the toolkit — the LLM doesn't see it.
    - An alias in **both** lists raises ``ValueError``.

    Aliases (the strings you put in the lists) are short for the snippet; the actual method
    names registered with the LLM are descriptive so the tool spec is self-explanatory:

    | Alias    | Registered tool name | What it does                            |
    | -------- | -------------------- | --------------------------------------- |
    | ``read``   | ``read_file``        | Read a file (line-numbered)             |
    | ``list``   | ``list_files``       | List a directory (recursive option)     |
    | ``search`` | ``search_content``   | Recursive content search (substring)    |
    | ``grep``   | ``grep_content``     | Regex search with line numbers          |
    | ``write``  | ``write_file``       | Create or overwrite a file (atomic)     |
    | ``edit``   | ``edit_file``        | Replace a substring (with ``replace_all``)|
    | ``move``   | ``move_file``        | Move or rename a file                   |
    | ``delete`` | ``delete_file``      | Delete a file                           |
    | ``shell``  | ``run_command``      | Run a shell command in ``root``         |

    Defaults:

    - When both lists are ``None``: reads (``read``, ``list``, ``search``) auto-pass,
      writes (``write``, ``edit``, ``move``, ``delete``, ``shell``) require confirmation.
      This is the safe-by-default surface meant for the homepage demo.
    - When only one is set: the other defaults to ``[]`` — you've taken control,
      and the surface is exactly what you specified.

    ``exclude_patterns`` is an access boundary for every path the agent names. A path is
    excluded when any component of the path as written, or of the file it resolves to,
    matches a pattern. Excluded paths are hidden from ``list_files`` and ``search_content``
    and are refused by ``read_file``, ``write_file``, ``edit_file``, ``move_file`` (source
    and destination), and ``delete_file`` with
    ``Error: <argument> is excluded from this workspace: <path>``. Naming an excluded
    directory in ``list_files`` or ``search_content`` is refused the same way. On a
    case-insensitive filesystem (macOS and Windows defaults) patterns match
    case-insensitively, so ``.ENV`` is refused there and a file stored as ``BUILD``
    matches the pattern ``build``. Each pattern matches one path component; a pattern
    containing a path separator raises ``ValueError``. Hard links to an excluded file are
    not detected. The default set covers common noise directories
    (``.venv``, ``.venvs``, ``.context``, ``.git``, ``__pycache__``, ``node_modules``,
    etc.), env files (``.env*``, ``*.env``) and the credential files a repository or a
    home directory conventionally holds — private keys and keystores (``*.pem``,
    ``*.key``, ``id_rsa*``), credential directories (``.ssh``, ``.aws``, ``.kube``),
    registry and host tokens (``.npmrc``, ``.netrc``, ``.git-credentials``), credential
    data files (``credentials.json``, ``secrets.yaml``, ``service_account*.json``) and
    Terraform inputs (``*.tfvars``). Deliberately absent are ``credentials.*`` and
    ``secrets.*``, which would also refuse ordinary source such as ``credentials.py``.
    Pass ``exclude_patterns=[...]`` to override, or ``exclude_patterns=[]`` to disable.

    An entry prefixed with ``!`` is an exemption: a component matching it is never
    excluded, whatever else it matches. The defaults use this to keep committed env
    templates readable (``!.env.example``, ``!.env.sample``, ``!.env.template``,
    ``!.env.dist``, ``!example.env``, ``!env.example``) while real env files stay
    refused. Exemptions are order-independent and always win; a bare ``!`` raises
    ``ValueError``. To drop them, filter the defaults:
    ``[p for p in DEFAULT_EXCLUDE_PATTERNS if not p.startswith("!")]``.

    ``allow_paths`` names workspace-relative files or directories that stay visible and
    reachable even when they match an exclude pattern, for example ``[".env.example"]``.
    Entries are literal paths, not patterns. A directory entry covers the files beneath
    it, and exclude patterns still apply to names beneath the entry:
    ``allow_paths=["build"]`` reaches ``build/index.html`` but not ``build/.env``. An
    allowed path beneath an excluded directory is reachable by name; recursive listings
    still prune the excluded directory.

    ``run_command`` runs a process with ``cwd=root`` and is outside the path and exclude
    checks; gate it with ``confirm``.

    Optional ``require_read_before_write=True`` blocks ``write_file`` / ``edit_file`` /
    ``move_file`` / ``delete_file`` on existing files until the agent has read them in
    this session. Catches the "agent hallucinated the file's contents" bug class.
    """

    READ_TOOLS: List[str] = ["read", "list", "search", "grep"]
    WRITE_TOOLS: List[str] = ["write", "edit", "move", "delete", "shell"]
    ALL_TOOLS: List[str] = READ_TOOLS + WRITE_TOOLS

    # Alias → registered tool name (the descriptive name the LLM sees in the tool spec).
    _ALIASES: Dict[str, str] = {
        "read": "read_file",
        "list": "list_files",
        "search": "search_content",
        "grep": "grep_content",
        "write": "write_file",
        "edit": "edit_file",
        "move": "move_file",
        "delete": "delete_file",
        "shell": "run_command",
    }

    def __init__(
        self,
        root: Optional[Union[str, Path]] = None,
        allowed: Optional[List[str]] = None,
        confirm: Optional[List[str]] = None,
        require_read_before_write: bool = False,
        max_file_lines: int = 100_000,
        max_file_length: int = 10_000_000,
        exclude_patterns: Optional[List[str]] = None,
        allow_paths: Optional[List[str]] = None,
        **kwargs,
    ):
        # Resolve root to an absolute path once — never re-read cwd later (reload-safe).
        if root is None:
            self.root: Path = Path.cwd().resolve()
        else:
            self.root = Path(root).resolve()

        self.max_file_lines = max_file_lines
        self.max_file_length = max_file_length
        self.require_read_before_write = require_read_before_write
        self.exclude_patterns: List[str] = _validate_exclude_patterns(exclude_patterns)
        _resolve_allow_paths(self.root, allow_paths)
        self.allow_paths: List[str] = list(allow_paths) if allow_paths else []
        # Components below root of each allow_paths entry, as written and resolved; rebuilt when allow_paths changes.
        self._allow_snapshot: Optional[Tuple[str, ...]] = None
        self._allowed_parts: List[Tuple[str, ...]] = []
        # Whether names that differ only by case are the same entry on root's filesystem.
        self._fold_case: Optional[bool] = None
        # Tracks which paths have been read this session — used by require_read_before_write.
        # Resolved absolute paths so move/rename interactions are unambiguous.
        self._read_paths: Set[Path] = set()

        resolved_allowed_aliases, resolved_confirm_aliases = self._resolve_partitions(allowed, confirm)

        # Translate aliases → method names. The LLM sees the descriptive names.
        resolved_allowed_methods = [self._ALIASES[a] for a in resolved_allowed_aliases]
        resolved_confirm_methods = [self._ALIASES[a] for a in resolved_confirm_aliases]

        registered = resolved_allowed_methods + resolved_confirm_methods
        sync_tools = [getattr(self, name) for name in registered]
        async_tools = [(getattr(self, "a" + name), name) for name in registered]

        # Only nudge the agent about edit_file when edit_file is actually
        # available — read-only surfaces (e.g. WikiContextProvider's read
        # sub-agent) shouldn't be told how to use a tool they don't have.
        edit_registered = "edit" in resolved_allowed_aliases or "edit" in resolved_confirm_aliases
        toolkit_kwargs: dict = {}
        if edit_registered:
            toolkit_kwargs["instructions"] = (
                "Always read_file before editing — the line-numbered output gives you "
                "the exact substring to pass to edit_file's old_str parameter. "
                "Do not guess file contents or pass line numbers to edit_file."
            )
            toolkit_kwargs["add_instructions"] = True

        super().__init__(
            name="workspace",
            tools=sync_tools,
            async_tools=async_tools,
            requires_confirmation_tools=resolved_confirm_methods,
            **toolkit_kwargs,
            **kwargs,
        )

        # Surface-drift guard: every alias must resolve to both a sync method and async
        # sibling on the class. Catches contributor bugs (added a method but forgot to
        # add the alias, or vice versa).
        for alias, method_name in self._ALIASES.items():
            assert callable(getattr(self, method_name, None)), (
                f"Workspace missing sync method '{method_name}' for alias '{alias}'"
            )
            assert callable(getattr(self, "a" + method_name, None)), (
                f"Workspace missing async method 'a{method_name}' for alias '{alias}'"
            )

    @classmethod
    def _resolve_partitions(
        cls,
        allowed: Optional[List[str]],
        confirm: Optional[List[str]],
    ) -> Tuple[List[str], List[str]]:
        """Resolve allowed / confirm alias lists into mutually-exclusive lists.

        See the class docstring for the resolution rules. Both lists hold *aliases*
        (e.g. ``"read"``, not ``"read_file"``).
        """
        # Reject obvious misuse early — these are short kwarg names so users may
        # reach for confirm=True or confirm="write" by mistake.
        for arg_name, arg_value in (("allowed", allowed), ("confirm", confirm)):
            if arg_value is not None and not isinstance(arg_value, list):
                raise TypeError(
                    f"`{arg_name}` must be a list of aliases, got {type(arg_value).__name__}: "
                    f"{arg_value!r}. Valid aliases: {cls.ALL_TOOLS}"
                )

        # Both None → safe defaults.
        if allowed is None and confirm is None:
            return list(cls.READ_TOOLS), list(cls.WRITE_TOOLS)

        # If one is set, the other defaults to [] — explicit user control means no
        # surprise mixing.
        if allowed is None:
            allowed = []
        if confirm is None:
            confirm = []

        valid = set(cls.ALL_TOOLS)
        unknown_allowed = set(allowed) - valid
        if unknown_allowed:
            raise ValueError(
                f"Unknown alias(es) in `allowed`: {sorted(unknown_allowed)}. Valid aliases: {cls.ALL_TOOLS}"
            )
        unknown_confirm = set(confirm) - valid
        if unknown_confirm:
            raise ValueError(
                f"Unknown alias(es) in `confirm`: {sorted(unknown_confirm)}. Valid aliases: {cls.ALL_TOOLS}"
            )
        overlap = set(allowed) & set(confirm)
        if overlap:
            raise ValueError(
                f"Alias(es) appear in both `allowed` and `confirm`: {sorted(overlap)}. "
                "They must be mutually exclusive — items in `allowed` auto-pass; "
                "items in `confirm` require approval."
            )
        return list(allowed), list(confirm)

    def _resolved_allow_parts(self) -> List[Tuple[str, ...]]:
        """Components below ``root`` of every ``allow_paths`` entry, as written and resolved."""
        snapshot = tuple(self.allow_paths)
        if snapshot != self._allow_snapshot:
            parts: List[Tuple[str, ...]] = []
            for pair in _resolve_allow_paths(self.root, list(snapshot)):
                for allowed in pair:
                    allowed_parts = self._relative_parts(allowed)
                    if allowed_parts and allowed_parts not in parts:
                        parts.append(allowed_parts)
            self._allowed_parts = parts
            self._allow_snapshot = snapshot
        return self._allowed_parts

    def _case_insensitive(self) -> bool:
        """Whether ``root`` sits on a case-insensitive filesystem; probed once the root exists."""
        if self._fold_case is None:
            if not self.root.exists():
                return sys.platform in ("darwin", "win32")
            self._fold_case = _is_case_insensitive_fs(self.root)
        return self._fold_case

    def _component_excluded(self, part: str) -> bool:
        """Whether one path component is excluded: it matches a deny pattern and no exemption.

        The patterns are compiled once per (list, case rule) rather than matched one at a
        time, because this runs for every entry of every listing and tree walk.
        """
        fold = "casefold" if self._case_insensitive() else "none"
        deny, exempt = compile_exclude_patterns(tuple(self.exclude_patterns), fold)
        if deny is None:
            return False
        folded = part.casefold() if fold == "casefold" else part
        return deny.match(folded) is not None and (exempt is None or exempt.match(folded) is None)

    def _relative_parts(self, path: Path) -> Optional[Tuple[str, ...]]:
        """Components of ``path`` below ``root``, or ``None`` when ``path`` is not under ``root``."""
        try:
            return path.relative_to(self.root).parts
        except ValueError:
            return None

    def _same_name(self, a: str, b: str) -> bool:
        return a.casefold() == b.casefold() if self._case_insensitive() else a == b

    def _allowed_depth(self, parts: Tuple[str, ...]) -> int:
        """Number of leading ``parts`` covered by the deepest ``allow_paths`` entry, or 0."""
        depth = 0
        for allowed_parts in self._resolved_allow_parts():
            if len(allowed_parts) > len(parts) or len(allowed_parts) <= depth:
                continue
            if all(self._same_name(a, b) for a, b in zip(allowed_parts, parts)):
                depth = len(allowed_parts)
        return depth

    def _is_excluded(self, path: Path) -> bool:
        """Return True if a component of ``path`` below ``root`` matches an exclude pattern.

        A component matching a ``!``-prefixed entry is exempt and never excluded.
        Components at or above an ``allow_paths`` entry covering ``path`` are not tested;
        components beneath a directory entry still are. On a case-insensitive filesystem
        patterns and ``allow_paths`` match case-insensitively.
        """
        parts = self._relative_parts(path)
        if not parts or not self.exclude_patterns:
            return False
        if not any(self._component_excluded(part) for part in parts):
            return False
        depth = self._allowed_depth(parts)
        if depth == 0:
            return True
        return any(self._component_excluded(part) for part in parts[depth:])

    def _hidden(self, entry: Path) -> bool:
        """Return True if a listing or search must skip ``entry``.

        An entry is hidden when it escapes ``root``, when its own path is excluded, or when
        a symlink in its path leads to an excluded target.
        """
        try:
            target = safe_join_relative_path(self.root, entry.relative_to(self.root).as_posix())
        except (PathSecurityError, ValueError):
            return True
        if self._is_excluded(entry):
            return True
        return target != entry and self._is_excluded(target)

    def _resolve(self, path: str, what: str = "path") -> Tuple[Optional[str], Path]:
        """Resolve a caller-supplied path inside ``root`` and apply the exclude boundary.

        Returns ``(error, resolved)``. ``error`` is ``None`` when the path may be used;
        otherwise it is the message to return to the caller. ``what`` names the argument
        in the message (``path``, ``directory``, ``src``, ``dst``). Root escapes and
        exclusions return distinct messages. The exclusion check tests the resolved target
        and, unless an ``allow_paths`` entry covers that target, the path as written. It
        runs before any existence check, so a refusal does not reveal whether the path
        exists.
        """
        safe, resolved = self._check_path(path, self.root)
        if not safe:
            log_error(f"Path escapes workspace: {path}")
            return f"Error: {what} escapes workspace root", resolved
        excluded = self._is_excluded(resolved)
        if not excluded:
            resolved_parts = self._relative_parts(resolved)
            covered = resolved_parts is not None and self._allowed_depth(resolved_parts) > 0
            excluded = not covered and self._is_excluded(_lexical_join(self.root, path))
        if excluded:
            log_warning(f"Refused excluded path: {path}")
            return f"Error: {what} is excluded from this workspace: {path}", resolved
        return None, resolved

    def _check_read_before_write(self, file_path: Path, op: str) -> Optional[str]:
        """If require_read_before_write is on, verify the file was read this session.

        Returns an error string if the check fails, or ``None`` if it passes (or
        the file is being newly created, which doesn't need a prior read).
        """
        if not self.require_read_before_write:
            return None
        if not file_path.exists():
            # Creating a new file is fine without a prior read.
            return None
        if file_path in self._read_paths:
            return None
        return (
            f"Error: require_read_before_write is enabled and {file_path.name} hasn't "
            f"been read this session. Call read_file first to confirm contents before "
            f"the {op}."
        )

    # ------------------------------------------------------------------
    # Read operations (auto-pass by default)
    # ------------------------------------------------------------------

    def read_file(
        self,
        path: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        encoding: str = "utf-8",
    ) -> str:
        """Read a file from the workspace, returning ``cat -n`` style line-numbered output.

        Each line is prefixed with its 1-indexed line number followed by a tab. The
        numbers reflect the actual line in the file — if you read lines 50-60, the
        first returned line is numbered 50. Pass these line numbers back to ``edit_file``
        when you want to make a targeted change.

        :param path: File path relative to the workspace root.
        :param start_line: Optional 1-indexed first line to return. If omitted with
            end_line, returns the entire file (subject to size limits).
        :param end_line: Optional 1-indexed last line to return (inclusive).
        :param encoding: Text encoding (default utf-8).
        :return: Line-numbered file contents (or selected range), or an error message
            starting with "Error".
        """
        try:
            log_debug(f"read_file: {path}")
            err, file_path = self._resolve(path)
            if err:
                return err
            if not file_path.is_file():
                return f"Error: file not found: {path}"
            contents = file_path.read_text(encoding=encoding)
            self._read_paths.add(file_path)
            if start_line is None and end_line is None:
                if len(contents) > self.max_file_length:
                    return (
                        f"Error: file too long ({len(contents)} chars > {self.max_file_length}). "
                        "Use start_line/end_line to read a chunk, "
                        "or use search_content to find specific text first."
                    )
                line_count = contents.count("\n") + 1
                if line_count > self.max_file_lines:
                    return (
                        f"Error: file too long ({line_count} lines > {self.max_file_lines}). "
                        "Use start_line/end_line to read a chunk, "
                        "or use search_content to find specific text first."
                    )
                return _format_with_line_numbers(contents, start_line=1)
            lines = contents.split("\n")
            start = start_line if start_line is not None else 1
            end = end_line if end_line is not None else len(lines)
            start_idx = max(0, start - 1)
            end_idx = min(len(lines), end)
            chunk = "\n".join(lines[start_idx:end_idx])
            return _format_with_line_numbers(chunk, start_line=start)
        except Exception as e:
            log_error(f"read_file failed: {e}")
            return f"Error reading file: {e}"

    def list_files(
        self,
        directory: str = ".",
        pattern: Optional[str] = None,
        recursive: bool = False,
        max_depth: int = 3,
    ) -> str:
        """List entries in a workspace directory.

        Each entry is returned as ``{"path", "type", "size"}`` so you can decide which
        files to read without a second call. ``type`` is ``"file"`` or ``"dir"``;
        ``size`` is a human-readable string for files and ``null`` for directories.

        For tree-style exploration of a project use ``recursive=True`` (defaults to
        depth 3). Excluded directories (``.venv``, ``.venvs``, ``.context``, ``.git``,
        ``node_modules``, etc.) are pruned unless covered by ``allow_paths``; naming one
        directly returns an error.

        :param directory: Subdirectory relative to the workspace root (default ".").
        :param pattern: Optional glob pattern to filter by (e.g. ``"*.py"``). When
            ``recursive=False`` patterns can include ``**`` for cross-directory globs.
            When ``recursive=True`` the pattern is matched against each entry name.
        :param recursive: If True, walk the directory tree up to ``max_depth`` levels deep.
        :param max_depth: Depth limit when ``recursive=True`` (default 3).
        :return: JSON string with keys ``directory``, ``pattern``, ``recursive``, and
            ``files`` (list of entry objects).
        """
        try:
            err, d = self._resolve(directory, what="directory")
            if err:
                return err
            if not d.is_dir():
                return f"Error: not a directory: {directory}"

            entries: List[Path] = []
            if recursive:
                # max_depth controls how many levels deep we return entries.
                # At the boundary (rel_depth == max_depth) we still enumerate
                # files and dirs at that level but stop recursing further.
                base_depth = len(d.parts)
                for dirpath, dirnames, filenames in os.walk(d):
                    rel_depth = len(Path(dirpath).parts) - base_depth
                    if rel_depth >= max_depth:
                        # Stop recursion but keep dir names for enumeration below.
                        visible_dirs = [name for name in dirnames if not self._is_excluded(Path(dirpath) / name)]
                        dirnames[:] = []
                    else:
                        dirnames[:] = [name for name in dirnames if not self._is_excluded(Path(dirpath) / name)]
                        visible_dirs = list(dirnames)
                    for name in filenames + visible_dirs:
                        full = Path(dirpath) / name
                        if self._hidden(full):
                            continue
                        if pattern and not fnmatch(name, pattern):
                            continue
                        entries.append(full)
            elif pattern:
                entries = [p for p in d.glob(pattern) if not self._hidden(p)]
            else:
                entries = [p for p in d.iterdir() if not self._hidden(p)]

            files = []
            for p in sorted(entries):
                try:
                    is_dir = p.is_dir()
                    size = None if is_dir else _format_size(p.stat().st_size)
                except OSError:
                    # Broken symlink or vanished file — skip silently.
                    continue
                files.append(
                    {
                        "path": p.relative_to(self.root).as_posix(),
                        "type": "dir" if is_dir else "file",
                        "size": size,
                    }
                )

            return json.dumps(
                {
                    "directory": directory,
                    "pattern": pattern,
                    "recursive": recursive,
                    "files": files,
                },
                indent=2,
            )
        except Exception as e:
            log_error(f"list_files failed: {e}")
            return f"Error listing files: {e}"

    def search_content(self, query: str, directory: str = ".", limit: int = 10) -> str:
        """Recursive case-insensitive content grep across text files in the workspace.

        Only text files (by extension) under 500KB are searched. Returns the first ``limit``
        matching files with a snippet around the first match in each.

        :param query: Substring to search for (case-insensitive).
        :param directory: Subdirectory to scope the search to (default ".").
        :param limit: Maximum number of matching files to return (default 10).
        :return: JSON string with keys ``query``, ``matches_found``, and ``files`` (a list of
            ``{"file", "size", "snippet"}`` objects).
        """
        try:
            if not query or not query.strip():
                return "Error: query cannot be empty"
            err, search_dir = self._resolve(directory, what="directory")
            if err:
                return err
            if not search_dir.is_dir():
                return f"Error: not a directory: {directory}"

            lower_query = query.lower()
            matches: List[dict] = []
            max_file_size = 500 * 1024
            walk_done = False

            for dirpath, dirnames, filenames in os.walk(search_dir):
                if walk_done:
                    break
                dirnames[:] = [name for name in dirnames if not self._is_excluded(Path(dirpath) / name)]
                for filename in filenames:
                    if len(matches) >= limit:
                        walk_done = True
                        break
                    file_path = Path(dirpath) / filename
                    if self._hidden(file_path):
                        continue
                    if file_path.suffix.lower() not in TEXT_EXTENSIONS:
                        continue
                    try:
                        if file_path.stat().st_size > max_file_size:
                            continue
                    except OSError:
                        continue
                    try:
                        content = file_path.read_text(encoding="utf-8", errors="ignore")
                    except Exception:
                        continue
                    if lower_query in content.lower():
                        rel_path = file_path.relative_to(self.root).as_posix()
                        matches.append(
                            {
                                "file": rel_path,
                                "size": _format_size(file_path.stat().st_size),
                                "snippet": _extract_snippet(content, query),
                            }
                        )
            return json.dumps({"query": query, "matches_found": len(matches), "files": matches}, indent=2)
        except Exception as e:
            log_error(f"search_content failed: {e}")
            return f"Error searching content: {e}"

    def grep_content(
        self,
        pattern: str,
        directory: str = ".",
        ignore_case: bool = False,
        context_lines: int = 0,
        files_only: bool = False,
        limit: int = 100,
    ) -> str:
        """Regex search with line numbers across text files in the workspace.

        Returns matches in ``path:line:text`` format, grouped by file with context lines.
        Use ``files_only=True`` for a quick list of matching files without content.

        :param pattern: Regex pattern to search for.
        :param directory: Subdirectory to scope the search to (default ".").
        :param ignore_case: Case-insensitive matching (default False).
        :param context_lines: Lines of context before and after each match (default 0).
        :param files_only: Return only file paths, not matching lines (default False).
        :param limit: Maximum number of matches to return (default 100).
        :return: Matching lines as ``path:line:text``, or file paths if ``files_only``.
        """
        try:
            if not pattern or not pattern.strip():
                return "Error: pattern cannot be empty"

            # 1. Compile regex
            flags = re.IGNORECASE if ignore_case else 0
            try:
                rx = re.compile(pattern, flags)
            except re.error as exc:
                return f"Error: invalid regex pattern: {exc}"

            # 2. Resolve directory
            err, search_dir = self._resolve(directory, what="directory")
            if err:
                return err
            if not search_dir.is_dir():
                return f"Error: not a directory: {directory}"

            max_file_size = 500 * 1024
            out_lines: List[str] = []
            files_with_matches: List[str] = []
            total_matches = 0

            # 3. Walk the directory tree
            for dirpath, dirnames, filenames in os.walk(search_dir):
                if total_matches >= limit:
                    break
                # Prune excluded directories
                dirnames[:] = [name for name in dirnames if not self._is_excluded(Path(dirpath) / name)]

                for filename in filenames:
                    if total_matches >= limit:
                        break
                    file_path = Path(dirpath) / filename

                    # Skip hidden/excluded files
                    if self._hidden(file_path):
                        continue
                    if file_path.suffix.lower() not in TEXT_EXTENSIONS:
                        continue
                    try:
                        if file_path.stat().st_size > max_file_size:
                            continue
                    except OSError:
                        continue

                    # Read and search
                    try:
                        content = file_path.read_text(encoding="utf-8", errors="ignore")
                    except Exception:
                        continue

                    lines = content.splitlines()
                    hits = [idx for idx, line in enumerate(lines) if rx.search(line)]

                    if not hits:
                        continue

                    rel_path = file_path.relative_to(self.root).as_posix()
                    files_with_matches.append(rel_path)

                    if files_only:
                        continue

                    # Collect matches with context
                    shown: Set[int] = set()
                    file_output: List[str] = []

                    for hit in hits:
                        if total_matches >= limit:
                            break
                        # Calculate context range
                        start = max(0, hit - context_lines)
                        end = min(len(lines), hit + context_lines + 1)

                        for j in range(start, end):
                            if j not in shown:
                                shown.add(j)
                                file_output.append(f"{rel_path}:{j + 1}:{lines[j]}")

                        total_matches += 1

                    if file_output:
                        out_lines.extend(file_output)
                        if context_lines > 0:
                            out_lines.append("--")

            # 4. Format output
            if files_only:
                if files_with_matches:
                    result = "\n".join(files_with_matches)
                    return f"{result}\n({len(files_with_matches)} files)"
                return f"No files match pattern: {pattern}"

            if out_lines:
                # Remove trailing separator
                if out_lines and out_lines[-1] == "--":
                    out_lines.pop()
                truncated = f"\n(showing {total_matches} matches, limit={limit})" if total_matches >= limit else ""
                return "\n".join(out_lines) + truncated
            return f"No matches for pattern: {pattern}"

        except Exception as e:
            log_error(f"grep_content failed: {e}")
            return f"Error in grep: {e}"

    # ------------------------------------------------------------------
    # Write operations (require confirmation by default)
    # ------------------------------------------------------------------

    def write_file(self, path: str, content: str, overwrite: bool = True, encoding: str = "utf-8") -> str:
        """Write a file to the workspace, creating parent directories if needed.

        Writes are atomic: content is written to a sibling ``.tmp`` file and renamed
        into place, so a crash mid-write can't leave a partially-written target.

        :param path: File path relative to the workspace root.
        :param content: Text content to write.
        :param overwrite: If False, fail when the file already exists (default True).
        :param encoding: Text encoding (default utf-8).
        :return: Success message including the path and byte count, or an error message.
        """
        try:
            err, file_path = self._resolve(path)
            if err:
                return err
            if file_path.exists() and not overwrite:
                return f"Error: file exists and overwrite=False: {path}"
            check_err = self._check_read_before_write(file_path, op="write")
            if check_err:
                return check_err
            if not file_path.parent.exists():
                file_path.parent.mkdir(parents=True, exist_ok=True)

            tmp_path = file_path.with_name(file_path.name + ".tmp")
            try:
                tmp_path.write_text(content, encoding=encoding)
                os.replace(tmp_path, file_path)
            finally:
                if tmp_path.exists():
                    tmp_path.unlink()
            # Treat write as a read for require_read_before_write — the agent now knows
            # the contents, so subsequent edits to the same path are fair game.
            self._read_paths.add(file_path)
            return f"Wrote {len(content)} chars to {path}"
        except Exception as e:
            log_error(f"write_file failed: {e}")
            return f"Error writing file: {e}"

    def edit_file(
        self,
        path: str,
        old_str: str,
        new_str: str,
        replace_all: bool = False,
        encoding: str = "utf-8",
    ) -> str:
        """Edit a file by replacing ``old_str`` with ``new_str``.

        By default ``old_str`` must match exactly once — fails if it appears zero or
        more than one times. Pass ``replace_all=True`` to replace every occurrence
        (useful for renames across a file).

        :param path: File path relative to the workspace root.
        :param old_str: Exact substring to replace.
        :param new_str: Replacement substring.
        :param replace_all: If True, replace every occurrence (default False).
        :param encoding: Text encoding (default utf-8).
        :return: Success message with the count, or an error if no matches (or, when
            ``replace_all=False``, multiple matches).
        """
        try:
            if not old_str:
                return "Error: old_str cannot be empty"
            err, file_path = self._resolve(path)
            if err:
                return err
            if not file_path.is_file():
                return f"Error: file not found: {path}"
            check_err = self._check_read_before_write(file_path, op="edit")
            if check_err:
                return check_err
            contents = file_path.read_text(encoding=encoding)
            count = contents.count(old_str)
            if count == 0:
                return f"Error: old_str not found in {path}"
            if count > 1 and not replace_all:
                return (
                    f"Error: old_str matches {count} times in {path}; "
                    "provide a more unique snippet or pass replace_all=True"
                )
            new_contents = contents.replace(old_str, new_str) if replace_all else contents.replace(old_str, new_str, 1)
            tmp_path = file_path.with_name(file_path.name + ".tmp")
            try:
                tmp_path.write_text(new_contents, encoding=encoding)
                os.replace(tmp_path, file_path)
            finally:
                if tmp_path.exists():
                    tmp_path.unlink()
            return f"Edited {path}: replaced {count if replace_all else 1} occurrence{'s' if (count if replace_all else 1) != 1 else ''}"
        except Exception as e:
            log_error(f"edit_file failed: {e}")
            return f"Error editing file: {e}"

    def move_file(self, src: str, dst: str, overwrite: bool = False) -> str:
        """Move or rename a file within the workspace.

        Both ``src`` and ``dst`` must resolve inside the workspace root. By default
        refuses to clobber an existing destination — pass ``overwrite=True`` to
        force.

        :param src: Source file path relative to the workspace root.
        :param dst: Destination path relative to the workspace root.
        :param overwrite: If True, replace ``dst`` if it already exists (default False).
        :return: Success message, or an error if either path escapes, src is missing,
            or dst exists and overwrite is False.
        """
        try:
            err, src_path = self._resolve(src, what="src")
            if err:
                return err
            err, dst_path = self._resolve(dst, what="dst")
            if err:
                return err
            if not src_path.exists():
                return f"Error: src not found: {src}"
            if src_path.is_dir():
                return f"Error: src is a directory, not a file: {src}"
            if dst_path.exists() and not overwrite:
                return f"Error: dst exists and overwrite=False: {dst}"
            check_err = self._check_read_before_write(src_path, op="move")
            if check_err:
                return check_err
            if not dst_path.parent.exists():
                dst_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(src_path, dst_path) if overwrite else src_path.rename(dst_path)
            # Carry the "has been read" status with the file.
            if src_path in self._read_paths:
                self._read_paths.discard(src_path)
                self._read_paths.add(dst_path)
            return f"Moved {src} -> {dst}"
        except Exception as e:
            log_error(f"move_file failed: {e}")
            return f"Error moving file: {e}"

    def delete_file(self, path: str) -> str:
        """Delete a file from the workspace. Refuses to delete directories.

        :param path: File path relative to the workspace root.
        :return: Success message, or an error if the path doesn't exist or is a directory.
        """
        try:
            err, file_path = self._resolve(path)
            if err:
                return err
            if not file_path.exists():
                return f"Error: file not found: {path}"
            if file_path.is_dir():
                return f"Error: path is a directory, not a file: {path}"
            check_err = self._check_read_before_write(file_path, op="delete")
            if check_err:
                return check_err
            file_path.unlink()
            self._read_paths.discard(file_path)
            return f"Deleted {path}"
        except Exception as e:
            log_error(f"delete_file failed: {e}")
            return f"Error deleting file: {e}"

    def run_command(self, args: List[str], tail: int = 100, timeout: int = 120) -> str:
        """Run a shell command in the workspace root and return its output.

        Args is a list of strings (e.g. ``["ls", "-la"]``) — the command is NOT
        invoked through a shell, so quoting/expansion are not interpreted. To use
        shell features, pass ``["bash", "-c", "your-command-here"]``.

        ANSI escape sequences (color codes, cursor moves) are stripped from output
        before truncation, so terminal-formatted output doesn't waste tokens.

        :param args: Command and arguments as a list of strings.
        :param tail: Maximum number of trailing lines of stdout (or stderr on error) to return.
        :param timeout: Maximum seconds to wait before killing the process (default 120).
        :return: Tailed stdout on success, or an error message including stderr on failure.
        """
        try:
            log_info(f"run_command: {args}")
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                cwd=str(self.root),
                timeout=timeout,
            )
            if result.returncode != 0:
                err = "\n".join(_strip_ansi(result.stderr).splitlines()[-tail:])
                return f"Error (exit {result.returncode}): {err}"
            return "\n".join(_strip_ansi(result.stdout).splitlines()[-tail:])
        except subprocess.TimeoutExpired:
            log_warning(f"run_command timed out after {timeout}s: {args}")
            return f"Error: command timed out after {timeout} seconds"
        except Exception as e:
            log_warning(f"run_command failed: {e}")
            return f"Error running command: {e}"

    # ------------------------------------------------------------------
    # Async siblings
    # ------------------------------------------------------------------

    async def aread_file(
        self,
        path: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        encoding: str = "utf-8",
    ) -> str:
        """Async variant of ``read_file``."""
        return await asyncio.to_thread(self.read_file, path, start_line, end_line, encoding)

    async def alist_files(
        self,
        directory: str = ".",
        pattern: Optional[str] = None,
        recursive: bool = False,
        max_depth: int = 3,
    ) -> str:
        """Async variant of ``list_files``."""
        return await asyncio.to_thread(self.list_files, directory, pattern, recursive, max_depth)

    async def asearch_content(self, query: str, directory: str = ".", limit: int = 10) -> str:
        """Async variant of ``search_content``."""
        return await asyncio.to_thread(self.search_content, query, directory, limit)

    async def agrep_content(
        self,
        pattern: str,
        directory: str = ".",
        ignore_case: bool = False,
        context_lines: int = 0,
        files_only: bool = False,
        limit: int = 100,
    ) -> str:
        """Async variant of ``grep_content``."""
        return await asyncio.to_thread(
            self.grep_content, pattern, directory, ignore_case, context_lines, files_only, limit
        )

    async def awrite_file(self, path: str, content: str, overwrite: bool = True, encoding: str = "utf-8") -> str:
        """Async variant of ``write_file``."""
        return await asyncio.to_thread(self.write_file, path, content, overwrite, encoding)

    async def aedit_file(
        self,
        path: str,
        old_str: str,
        new_str: str,
        replace_all: bool = False,
        encoding: str = "utf-8",
    ) -> str:
        """Async variant of ``edit_file``."""
        return await asyncio.to_thread(self.edit_file, path, old_str, new_str, replace_all, encoding)

    async def amove_file(self, src: str, dst: str, overwrite: bool = False) -> str:
        """Async variant of ``move_file``."""
        return await asyncio.to_thread(self.move_file, src, dst, overwrite)

    async def adelete_file(self, path: str) -> str:
        """Async variant of ``delete_file``."""
        return await asyncio.to_thread(self.delete_file, path)

    async def arun_command(self, args: List[str], tail: int = 100, timeout: int = 120) -> str:
        """Async variant of ``run_command`` using ``asyncio.create_subprocess_exec``."""
        try:
            log_info(f"arun_command: {args}")
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.root),
            )
            try:
                stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                log_warning(f"arun_command timed out after {timeout}s: {args}")
                return f"Error: command timed out after {timeout} seconds"
            stdout = stdout_b.decode("utf-8", errors="replace") if stdout_b else ""
            stderr = stderr_b.decode("utf-8", errors="replace") if stderr_b else ""
            if proc.returncode != 0:
                err = "\n".join(_strip_ansi(stderr).splitlines()[-tail:])
                return f"Error (exit {proc.returncode}): {err}"
            return "\n".join(_strip_ansi(stdout).splitlines()[-tail:])
        except Exception as e:
            log_warning(f"arun_command failed: {e}")
            return f"Error running command: {e}"
