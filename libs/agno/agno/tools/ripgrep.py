"""RipgrepTools — fast code search using ripgrep (rg).

A toolkit for searching codebases using ripgrep, a fast regex search tool.
Provides grep, search, list, and read operations optimized for large codebases.

Requires ripgrep to be installed: https://github.com/BurntSushi/ripgrep

    brew install ripgrep    # macOS
    apt install ripgrep     # Debian/Ubuntu
    cargo install ripgrep   # Rust

Example:
    from agno.agent import Agent
    from agno.tools.ripgrep import RipgrepTools

    agent = Agent(
        tools=[RipgrepTools(root="./my-project")],
    )
"""

import asyncio
import json
import subprocess
from pathlib import Path
from shutil import which
from typing import Any, List, Optional, Set, Tuple, Union

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_warning

# Text file extensions to search (same as Workspace toolkit)
TEXT_EXTENSIONS = {
    ".md",
    ".mdx",
    ".txt",
    ".csv",
    ".json",
    ".yaml",
    ".yml",
    ".xml",
    ".html",
    ".rst",
    ".log",
    ".toml",
    ".cfg",
    ".ini",
    ".env",
    ".editorconfig",
    ".example",
    ".sample",
    ".template",
    ".dist",
    ".py",
    ".pyi",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".mjs",
    ".cjs",
    ".css",
    ".scss",
    ".less",
    ".vue",
    ".svelte",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".cc",
    ".cxx",
    ".rs",
    ".go",
    ".zig",
    ".java",
    ".kt",
    ".kts",
    ".scala",
    ".groovy",
    ".gradle",
    ".cs",
    ".fs",
    ".vb",
    ".rb",
    ".php",
    ".pl",
    ".pm",
    ".lua",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".ps1",
    ".bat",
    ".cmd",
    ".sql",
    ".graphql",
    ".gql",
    ".proto",
    ".thrift",
    ".dockerfile",
    ".containerfile",
    ".tf",
    ".hcl",
    ".r",
    ".R",
    ".jl",
    ".ex",
    ".exs",
    ".erl",
    ".hrl",
    ".clj",
    ".cljs",
    ".swift",
    ".m",
    ".mm",
    ".dart",
    ".nim",
    ".v",
    ".asm",
    ".s",
}


class RipgrepTools(Toolkit):
    """Fast code search toolkit using ripgrep.

    Args:
        root: Root directory to search in.
        enable_grep: Enable grep_content tool for regex search. Default True.
        enable_search: Enable search_content tool for substring search. Default True.
        enable_list: Enable list_files tool. Default True.
        enable_read: Enable read_file tool. Default True.
        max_results: Maximum results to return per search. Default 100.
        max_file_size: Skip files larger than this (bytes). Default 500KB.
        timeout: Subprocess timeout in seconds. Default 30.
        respect_gitignore: Respect .gitignore rules. Default True.
        include_hidden: Include hidden files/directories. Default False.
    """

    def __init__(
        self,
        root: str | Path = ".",
        enable_grep: bool = True,
        enable_search: bool = True,
        enable_list: bool = True,
        enable_read: bool = True,
        max_results: int = 100,
        max_file_size: int = 500 * 1024,
        timeout: int = 30,
        respect_gitignore: bool = True,
        include_hidden: bool = False,
        **kwargs: Any,
    ):
        self.root = Path(root).resolve()
        self.max_results = max_results
        self.max_file_size = max_file_size
        self.timeout = timeout
        self.respect_gitignore = respect_gitignore
        self.include_hidden = include_hidden

        # Check ripgrep availability
        self._rg_path: Optional[str] = None
        self._check_ripgrep()

        tools: List[Any] = []
        if enable_grep:
            tools.append(self.grep_content)
        if enable_search:
            tools.append(self.search_content)
        if enable_list:
            tools.append(self.list_files)
        if enable_read:
            tools.append(self.read_file)

        super().__init__(name="ripgrep", tools=tools, **kwargs)

    def _check_ripgrep(self) -> None:
        """Check if ripgrep is installed."""
        self._rg_path = which("rg")
        if not self._rg_path:
            log_warning(
                "ripgrep (rg) not found. Install it: brew install ripgrep (macOS) "
                "or apt install ripgrep (Linux). Tools will return errors."
            )

    def _build_base_args(self) -> List[str]:
        """Build common ripgrep arguments."""
        if not self._rg_path:
            raise RuntimeError("ripgrep not installed")

        args = [self._rg_path]

        # Gitignore handling
        if not self.respect_gitignore:
            args.append("--no-ignore")

        # Hidden files
        if self.include_hidden:
            args.append("--hidden")

        # Max file size
        args.extend(["--max-filesize", f"{self.max_file_size}"])

        return args

    def _build_type_args(self) -> List[str]:
        """Build ripgrep type arguments for code files.

        Uses the 'include' directive to define a custom 'code' type
        that includes all built-in types, then adds extra extensions.
        This is much faster than 90+ individual glob patterns.
        """
        # Built-in types to include
        builtin_types = [
            "py",
            "js",
            "ts",
            "go",
            "rust",
            "java",
            "c",
            "cpp",
            "css",
            "html",
            "json",
            "yaml",
            "markdown",
            "sh",
            "sql",
            "ruby",
            "php",
            "lua",
            "scala",
            "kotlin",
            "swift",
            "r",
            "dart",
            "nim",
            "zig",
            "protobuf",
            "graphql",
            "toml",
            "xml",
        ]

        # Extra extensions without built-in types
        extra_exts = [
            "*.cfg",
            "*.ini",
            "*.env",
            "*.jl",
            "*.ex",
            "*.exs",
            "*.erl",
            "*.hrl",
            "*.clj",
            "*.cljs",
            "*.v",
            "*.asm",
            "*.s",
            "*.thrift",
            "*.tf",
            "*.hcl",
        ]

        args = []

        # Create a custom 'code' type that includes all built-in types
        include_types = ",".join(builtin_types)
        args.extend(["--type-add", f"code:include:{include_types}"])

        # Add extra extensions to the 'code' type
        for ext in extra_exts:
            args.extend(["--type-add", f"code:{ext}"])

        # Use only the 'code' type
        args.extend(["-t", "code"])

        return args

    def _resolve_path(self, path: str) -> Tuple[Optional[str], Path]:
        """Resolve a path relative to root, with security check."""
        try:
            resolved = (self.root / path).resolve()
            # Security: ensure path is under root
            resolved.relative_to(self.root)
            return None, resolved
        except ValueError:
            return f"Error: path escapes root directory: {path}", self.root

    async def _async_run(self, args: List[str]) -> subprocess.CompletedProcess:
        """Run ripgrep asynchronously for better concurrency."""
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.root,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=self.timeout,
        )
        return subprocess.CompletedProcess(
            args=args,
            returncode=proc.returncode or 0,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
        )

    def grep_content(
        self,
        pattern: Union[str, List[str]],
        directory: str = ".",
        context_lines: int = 0,
        limit: int = 100,
    ) -> str:
        """Regex search with line numbers across text files.

        Args:
            pattern: Regex pattern(s) to search for. Can be a single string
                or a list of patterns (batched into one subprocess call).
            directory: Subdirectory to search in (relative to root).
            context_lines: Lines of context before/after match. Default 0.
            limit: Maximum matches to return. Default 100.

        Returns:
            JSON with pattern, total_matches, truncated, and matches list.
        """
        if not self._rg_path:
            return json.dumps({"error": "ripgrep not installed"})

        # Normalize patterns to list
        patterns = [pattern] if isinstance(pattern, str) else list(pattern)
        patterns = [p for p in patterns if p and p.strip()]
        if not patterns:
            return json.dumps({"error": "pattern cannot be empty"})

        err, search_dir = self._resolve_path(directory)
        if err:
            return json.dumps({"error": err})

        limit = min(limit, self.max_results)

        try:
            args = self._build_base_args()
            args.extend(
                [
                    "--json",
                    "--ignore-case",
                    "--max-count",
                    str(limit * 2),  # Get extra for dedup
                ]
            )

            if context_lines > 0:
                args.extend(["--context", str(context_lines)])

            args.extend(self._build_type_args())

            # Add patterns with -e flag (allows multiple patterns in one call)
            for p in patterns:
                args.extend(["-e", p])

            args.append(str(search_dir))

            log_debug(f"Running: {' '.join(args[:10])}...")

            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=self.root,
            )

            # Parse JSON output
            matches: List[dict] = []
            total_matches = 0
            seen_lines: Set[Tuple[str, int]] = set()

            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                entry_type = entry.get("type")
                if entry_type not in ("match", "context"):
                    continue

                data = entry.get("data", {})
                path_obj = data.get("path", {})
                file_path = path_obj.get("text", "")

                # Make path relative to root
                try:
                    rel_path = Path(file_path).relative_to(self.root).as_posix()
                except ValueError:
                    rel_path = file_path

                line_num = data.get("line_number", 0)
                lines_data = data.get("lines", {})
                text = lines_data.get("text", "").rstrip("\n")

                key = (rel_path, line_num)
                if key not in seen_lines:
                    seen_lines.add(key)
                    matches.append({"file": rel_path, "line": line_num, "text": text})
                    if entry_type == "match":
                        total_matches += 1
                        if total_matches >= limit:
                            break

            return json.dumps(
                {
                    "pattern": pattern,
                    "total_matches": total_matches,
                    "truncated": total_matches >= limit,
                    "matches": matches,
                },
                indent=2,
            )

        except subprocess.TimeoutExpired:
            return json.dumps({"error": f"search timed out after {self.timeout}s"})
        except Exception as e:
            log_error(f"grep_content failed: {e}")
            return json.dumps({"error": str(e)})

    def search_content(
        self,
        query: str,
        directory: str = ".",
        limit: int = 20,
    ) -> str:
        """Substring search across text files.

        Args:
            query: Text to search for (literal, not regex).
            directory: Subdirectory to search in.
            limit: Maximum files to return. Default 20.

        Returns:
            JSON with query, matches_found, and files list.
        """
        if not self._rg_path:
            return json.dumps({"error": "ripgrep not installed"})

        if not query or not query.strip():
            return json.dumps({"error": "query cannot be empty"})

        err, search_dir = self._resolve_path(directory)
        if err:
            return json.dumps({"error": err})

        limit = min(limit, self.max_results)

        try:
            args = self._build_base_args()
            args.extend(
                [
                    "--json",
                    "--fixed-strings",  # Literal search, not regex
                    "--ignore-case",
                    "--max-count",
                    "3",  # Max matches per file
                ]
            )
            args.extend(self._build_type_args())
            args.append(query)
            args.append(str(search_dir))

            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=self.root,
            )

            # Group matches by file
            files_dict: dict = {}
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if entry.get("type") != "match":
                    continue

                data = entry.get("data", {})
                path_obj = data.get("path", {})
                file_path = path_obj.get("text", "")

                try:
                    rel_path = Path(file_path).relative_to(self.root).as_posix()
                except ValueError:
                    rel_path = file_path

                if rel_path not in files_dict:
                    if len(files_dict) >= limit:
                        break
                    files_dict[rel_path] = {
                        "path": rel_path,
                        "snippets": [],
                    }

                lines_data = data.get("lines", {})
                text = lines_data.get("text", "").rstrip("\n")[:200]
                line_num = data.get("line_number", 0)
                files_dict[rel_path]["snippets"].append(f"L{line_num}: {text}")

            return json.dumps(
                {
                    "query": query,
                    "matches_found": len(files_dict),
                    "files": list(files_dict.values()),
                },
                indent=2,
            )

        except subprocess.TimeoutExpired:
            return json.dumps({"error": f"search timed out after {self.timeout}s"})
        except Exception as e:
            log_error(f"search_content failed: {e}")
            return json.dumps({"error": str(e)})

    def list_files(
        self,
        directory: str = ".",
        pattern: Optional[str] = None,
        limit: int = 200,
    ) -> str:
        """List files in directory.

        Args:
            directory: Directory to list (relative to root).
            pattern: Optional glob pattern to filter (e.g., "*.py").
            limit: Maximum files to return. Default 200.

        Returns:
            JSON with directory, count, and files list.
        """
        if not self._rg_path:
            return json.dumps({"error": "ripgrep not installed"})

        err, search_dir = self._resolve_path(directory)
        if err:
            return json.dumps({"error": err})

        if not search_dir.is_dir():
            return json.dumps({"error": f"not a directory: {directory}"})

        try:
            args = self._build_base_args()
            args.append("--files")

            if pattern:
                args.extend(["--glob", pattern])

            args.append(str(search_dir))

            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=self.root,
            )

            files = []
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                try:
                    rel_path = Path(line).relative_to(self.root).as_posix()
                except ValueError:
                    rel_path = line
                files.append(rel_path)
                if len(files) >= limit:
                    break

            return json.dumps(
                {
                    "directory": directory,
                    "count": len(files),
                    "truncated": len(files) >= limit,
                    "files": files,
                },
                indent=2,
            )

        except subprocess.TimeoutExpired:
            return json.dumps({"error": f"list timed out after {self.timeout}s"})
        except Exception as e:
            log_error(f"list_files failed: {e}")
            return json.dumps({"error": str(e)})

    def read_file(
        self,
        path: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
    ) -> str:
        """Read file contents with optional line range.

        Args:
            path: File path relative to root.
            start_line: First line to read (1-indexed). Default: start of file.
            end_line: Last line to read (1-indexed). Default: end of file.

        Returns:
            File contents with line numbers, or error message.
        """
        # Note: ripgrep can't read files, so we use Python
        err, file_path = self._resolve_path(path)
        if err:
            return err

        if not file_path.exists():
            return f"Error: file not found: {path}"

        if not file_path.is_file():
            return f"Error: not a file: {path}"

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"Error reading file: {e}"

        lines = content.splitlines()
        total_lines = len(lines)

        # Apply line range
        start = (start_line - 1) if start_line and start_line > 0 else 0
        end = end_line if end_line and end_line <= total_lines else total_lines

        selected = lines[start:end]

        # Format with line numbers
        output_lines = []
        for i, line in enumerate(selected, start=start + 1):
            output_lines.append(f"{i}\t{line}")

        return "\n".join(output_lines)
