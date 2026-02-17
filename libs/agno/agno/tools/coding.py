import functools
import shlex
import subprocess
import tempfile
from pathlib import Path
from textwrap import dedent
from typing import Any, List, Optional, Union

from agno.tools import Toolkit
from agno.utils.log import log_error, log_info, logger


@functools.lru_cache(maxsize=None)
def _warn_coding_tools() -> None:
    logger.warning("CodingTools can run arbitrary shell commands, please provide human supervision.")


class CodingTools(Toolkit):
    """A minimal, powerful toolkit for coding agents.

    Provides four core tools (read, edit, write, shell) and three optional
    exploration tools (grep, find, ls). With these primitives, an agent can
    perform any file operation, run tests, use git, install packages, search
    codebases, and more.

    Inspired by the Pi coding agent's philosophy: a small number of composable
    tools is more powerful than many specialized ones.
    """

    DEFAULT_ALLOWED_COMMANDS: List[str] = [
        "python",
        "python3",
        "pytest",
        "pip",
        "pip3",
        "cat",
        "head",
        "tail",
        "wc",
        "ls",
        "find",
        "grep",
        "mkdir",
        "rm",
        "mv",
        "cp",
        "touch",
        "echo",
        "printf",
        "git",
        "chmod",
        "diff",
        "sort",
        "uniq",
        "tr",
        "cut",
    ]

    DEFAULT_INSTRUCTIONS = dedent("""\
        You have access to coding tools: read_file, edit_file, write_file, and run_shell.
        With these tools, you can perform any coding task including reading code, making edits,
        creating files, running tests, using git, installing packages, and searching codebases.

        ## Tool Usage Guidelines

        **read_file** - Read files with line numbers. Use offset and limit to paginate large files.
        - Always read a file before editing it to understand its current contents.
        - Use the line numbers in the output to understand the file structure.

        **edit_file** - Make precise edits using exact text matching (find and replace).
        - The old_text must match exactly one location in the file, including whitespace and indentation.
        - Include enough surrounding context in old_text to ensure a unique match.
        - Prefer small, focused edits over rewriting entire files.
        - If an edit fails due to multiple matches, include more surrounding lines in old_text.

        **write_file** - Create new files or overwrite existing ones entirely.
        - Use this for creating new files. For modifying existing files, prefer edit_file.
        - Parent directories are created automatically.

        **run_shell** - Execute shell commands with timeout protection.
        - Use this for: running tests, git operations, installing packages, searching files (grep/find),
          checking system state, compiling code, and any other command-line task.
        - Commands run from the base directory.
        - Output is truncated if too long; the full output is saved to a temp file.

        ## Best Practices
        - Read before editing: always read_file before edit_file to see current contents.
        - Make small, incremental edits rather than rewriting entire files.
        - Run tests after making changes to verify correctness.\
    """)

    EXPLORATION_INSTRUCTIONS = dedent("""\

        **grep** - Search file contents for a pattern with line numbers.
        - Use for finding code patterns, function definitions, imports, etc.
        - Supports regex patterns and case-insensitive search.
        - Use the include parameter to filter by file type (e.g. "*.py").

        **find** - Search for files by glob pattern.
        - Use for discovering files in the project structure.
        - Supports recursive patterns like "**/*.py".

        **ls** - List directory contents.
        - Use for quick directory exploration.
        - Directories are shown with a trailing /.\
    """)

    def __init__(
        self,
        base_dir: Optional[Union[Path, str]] = None,
        restrict_to_base_dir: bool = True,
        max_lines: int = 2000,
        max_bytes: int = 50_000,
        shell_timeout: int = 120,
        enable_read_file: bool = True,
        enable_edit_file: bool = True,
        enable_write_file: bool = True,
        enable_run_shell: bool = True,
        enable_grep: bool = False,
        enable_find: bool = False,
        enable_ls: bool = False,
        instructions: Optional[str] = None,
        add_instructions: bool = True,
        all: bool = False,
        allowed_commands: Optional[List[str]] = None,
        **kwargs: Any,
    ):
        """Initialize CodingTools.

        Args:
            base_dir: Root directory for file operations. Defaults to cwd.
            restrict_to_base_dir: If True, file and shell operations cannot escape base_dir.
            max_lines: Maximum lines to return before truncating (default 2000).
            max_bytes: Maximum bytes to return before truncating (default 50KB).
            shell_timeout: Timeout in seconds for shell commands (default 120).
            enable_read_file: Enable the read_file tool.
            enable_edit_file: Enable the edit_file tool.
            enable_write_file: Enable the write_file tool.
            enable_run_shell: Enable the run_shell tool.
            enable_grep: Enable the grep tool (disabled by default).
            enable_find: Enable the find tool (disabled by default).
            enable_ls: Enable the ls tool (disabled by default).
            instructions: Custom instructions for the LLM. Uses defaults if None.
            add_instructions: Whether to add instructions to the agent's system message.
            all: Enable all tools regardless of individual flags.
            allowed_commands: List of allowed shell command names when restrict_to_base_dir is True.
                Defaults to DEFAULT_ALLOWED_COMMANDS. Set to None explicitly after init to disable.
        """
        self.base_dir: Path = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
        self.restrict_to_base_dir = restrict_to_base_dir
        self.allowed_commands: Optional[List[str]] = (
            allowed_commands if allowed_commands is not None else self.DEFAULT_ALLOWED_COMMANDS
        )
        self.max_lines = max_lines
        self.max_bytes = max_bytes
        self.shell_timeout = shell_timeout
        self._temp_files: List[str] = []

        import atexit

        atexit.register(self._cleanup_temp_files)

        has_exploration = all or enable_grep or enable_find or enable_ls

        if instructions is None:
            resolved_instructions = self.DEFAULT_INSTRUCTIONS
            if has_exploration:
                resolved_instructions += self.EXPLORATION_INSTRUCTIONS
        else:
            resolved_instructions = instructions

        tools: List[Any] = []
        if all or enable_read_file:
            tools.append(self.read_file)
        if all or enable_edit_file:
            tools.append(self.edit_file)
        if all or enable_write_file:
            tools.append(self.write_file)
        if all or enable_run_shell:
            tools.append(self.run_shell)
        if all or enable_grep:
            tools.append(self.grep)
        if all or enable_find:
            tools.append(self.find)
        if all or enable_ls:
            tools.append(self.ls)

        super().__init__(
            name="coding_tools",
            tools=tools,
            instructions=resolved_instructions,
            add_instructions=add_instructions,
            **kwargs,
        )

    def _truncate_output(self, text: str) -> tuple:
        """Truncate text to configured limits.

        Returns:
            Tuple of (possibly truncated text, was_truncated, total_line_count).
        """
        lines = text.split("\n")
        total_lines = len(lines)
        was_truncated = False

        if total_lines > self.max_lines:
            lines = lines[: self.max_lines]
            was_truncated = True

        result = "\n".join(lines)

        if len(result.encode("utf-8", errors="replace")) > self.max_bytes:
            # Truncate by bytes: find last complete line within limit
            truncated_lines = []
            current_bytes = 0
            for line in lines:
                line_bytes = len((line + "\n").encode("utf-8", errors="replace"))
                if current_bytes + line_bytes > self.max_bytes:
                    break
                truncated_lines.append(line)
                current_bytes += line_bytes
            result = "\n".join(truncated_lines)
            was_truncated = True

        return result, was_truncated, total_lines

    def _cleanup_temp_files(self) -> None:
        """Remove temporary files created during shell output truncation."""
        for path in self._temp_files:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass
        self._temp_files.clear()

    # Shell operators that enable command chaining or substitution
    _DANGEROUS_PATTERNS: List[str] = ["&&", "||", ";", "|", "$(", "`", ">", ">>", "<"]

    def _check_command(self, command: str) -> Optional[str]:
        """Check if a shell command is safe to execute.

        When restrict_to_base_dir is True, this method:
        1. Blocks shell metacharacters that enable chaining/substitution.
        2. Validates the command name against the allowed_commands list (if set).
        3. Checks that path-like tokens don't escape the base directory.

        Returns an error message if a violation is found, None if safe.
        """
        if not self.restrict_to_base_dir:
            return None

        # Block shell operators that enable chaining/substitution
        for pattern in self._DANGEROUS_PATTERNS:
            if pattern in command:
                return f"Error: Shell operator '{pattern}' is not allowed in restricted mode."

        try:
            tokens = shlex.split(command)
        except ValueError:
            return "Error: Could not parse shell command."

        # Validate command against allowlist
        if self.allowed_commands is not None and tokens:
            cmd = tokens[0]
            cmd_base = Path(cmd).name  # Handle /usr/bin/python -> python
            if cmd_base not in self.allowed_commands:
                return f"Error: Command '{cmd_base}' is not in the allowed commands list."

        for i, token in enumerate(tokens):
            # Skip the command itself (already validated by allowlist above)
            if i == 0:
                continue
            # Skip flags
            if token.startswith("-"):
                continue

            # Check tokens that look like paths
            if "/" in token or token == "..":
                try:
                    # Resolve relative to base_dir
                    if token.startswith("/"):
                        resolved = Path(token).resolve()
                    else:
                        resolved = (self.base_dir / token).resolve()

                    # Check if resolved path is within base_dir
                    try:
                        resolved.relative_to(self.base_dir)
                    except ValueError:
                        return f"Error: Command references path outside base directory: {token}"
                except (OSError, RuntimeError):
                    continue

        return None

    def read_file(self, file_path: str, offset: int = 0, limit: Optional[int] = None) -> str:
        """Read the contents of a file with line numbers.

        Returns file contents with line numbers prefixed to each line. Supports
        pagination via offset and limit for large files. Output is truncated if
        it exceeds the configured limits.

        :param file_path: Path to the file to read (relative to base_dir or absolute).
        :param offset: Line number to start reading from (0-indexed). Default 0.
        :param limit: Maximum number of lines to read. Defaults to max_lines setting.
        :return: File contents with line numbers, or an error message.
        """
        try:
            safe, resolved_path = self._check_path(file_path, self.base_dir, self.restrict_to_base_dir)
            if not safe:
                return f"Error: Path '{file_path}' is outside the allowed base directory"

            if not resolved_path.exists():
                return f"Error: File not found: {file_path}"

            if not resolved_path.is_file():
                return f"Error: Not a file: {file_path}"

            # Detect binary files
            try:
                with open(resolved_path, "rb") as f:
                    chunk = f.read(8192)
                    if b"\x00" in chunk:
                        return f"Error: Binary file detected: {file_path}"
            except Exception:
                pass

            contents = resolved_path.read_text(encoding="utf-8", errors="replace")

            if not contents:
                return f"File is empty: {file_path}"

            lines = contents.split("\n")
            total_lines = len(lines)

            # Apply offset and limit
            effective_limit = limit if limit is not None else self.max_lines
            selected_lines = lines[offset : offset + effective_limit]

            # Format with line numbers
            # Calculate width for line number alignment
            max_line_num = offset + len(selected_lines)
            num_width = max(len(str(max_line_num)), 4)

            formatted_lines = []
            for i, line in enumerate(selected_lines):
                line_num = offset + i + 1  # 1-based
                formatted_lines.append(f"{line_num:>{num_width}} | {line}")

            output = "\n".join(formatted_lines)

            # Apply truncation
            output, was_truncated, _ = self._truncate_output(output)

            # Add summary footer
            shown_start = offset + 1
            shown_end = offset + len(selected_lines)
            if was_truncated or shown_end < total_lines or offset > 0:
                output += f"\n[Showing lines {shown_start}-{shown_end} of {total_lines} total]"

            return output

        except UnicodeDecodeError:
            return f"Error: Cannot decode file as text: {file_path}"
        except PermissionError:
            return f"Error: Permission denied: {file_path}"
        except Exception as e:
            log_error(f"Error reading file: {e}")
            return f"Error reading file: {e}"

    def edit_file(self, file_path: str, old_text: str, new_text: str) -> str:
        """Edit a file by replacing an exact text match with new text.

        The old_text must match exactly one location in the file. If it matches
        zero or multiple locations, the edit is rejected with an error message.
        Returns a unified diff showing the change.

        :param file_path: Path to the file to edit (relative to base_dir or absolute).
        :param old_text: The exact text to find and replace. Must match uniquely.
        :param new_text: The text to replace old_text with.
        :return: A unified diff of the change, or an error message.
        """
        try:
            safe, resolved_path = self._check_path(file_path, self.base_dir, self.restrict_to_base_dir)
            if not safe:
                return f"Error: Path '{file_path}' is outside the allowed base directory"

            if not resolved_path.exists():
                return f"Error: File not found: {file_path}"

            if not resolved_path.is_file():
                return f"Error: Not a file: {file_path}"

            if not old_text:
                return "Error: old_text cannot be empty"

            if old_text == new_text:
                return "No changes needed: old_text and new_text are identical"

            contents = resolved_path.read_text(encoding="utf-8")

            # Count occurrences
            count = contents.count(old_text)

            if count == 0:
                return (
                    f"Error: old_text not found in {file_path}. "
                    "Make sure the text matches exactly (including whitespace and indentation)."
                )

            if count > 1:
                return (
                    f"Error: old_text matches {count} locations in {file_path}. "
                    "Provide more surrounding context to make the match unique."
                )

            # Perform the replacement
            new_contents = contents.replace(old_text, new_text, 1)

            # Write the file
            resolved_path.write_text(new_contents, encoding="utf-8")

            # Generate unified diff
            import difflib

            old_lines = contents.splitlines(keepends=True)
            new_lines = new_contents.splitlines(keepends=True)

            diff = difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"a/{file_path}",
                tofile=f"b/{file_path}",
                n=3,
            )
            diff_output = "".join(diff)

            if not diff_output:
                return "Edit applied but no visible diff generated"

            # Truncate if needed
            diff_output, was_truncated, total_lines = self._truncate_output(diff_output)
            if was_truncated:
                diff_output += f"\n[Diff truncated: {total_lines} lines total]"

            log_info(f"Edited {file_path}")
            return diff_output

        except PermissionError:
            return f"Error: Permission denied: {file_path}"
        except Exception as e:
            log_error(f"Error editing file: {e}")
            return f"Error editing file: {e}"

    def write_file(self, file_path: str, contents: str) -> str:
        """Create or overwrite a file with the given contents.

        Parent directories are created automatically if they do not exist.

        :param file_path: Path to the file to write (relative to base_dir or absolute).
        :param contents: The full contents to write to the file.
        :return: A success message with the file path, or an error message.
        """
        try:
            safe, resolved_path = self._check_path(file_path, self.base_dir, self.restrict_to_base_dir)
            if not safe:
                return f"Error: Path '{file_path}' is outside the allowed base directory"

            # Create parent directories
            if not resolved_path.parent.exists():
                resolved_path.parent.mkdir(parents=True, exist_ok=True)

            resolved_path.write_text(contents, encoding="utf-8")

            line_count = len(contents.split("\n"))
            log_info(f"Wrote {file_path}")
            return f"Wrote {line_count} lines to {file_path}"

        except PermissionError:
            return f"Error: Permission denied: {file_path}"
        except Exception as e:
            log_error(f"Error writing file: {e}")
            return f"Error writing file: {e}"

    def run_shell(self, command: str, timeout: Optional[int] = None) -> str:
        """Execute a shell command and return its output.

        Runs the command as a string via the system shell. Output (stdout + stderr)
        is truncated if it exceeds the configured limits. When output is truncated,
        the full output is saved to a temporary file and its path is included in
        the response.

        :param command: The shell command to execute as a single string.
        :param timeout: Timeout in seconds. Defaults to the toolkit's shell_timeout.
        :return: Command output (stdout and stderr combined), or an error message.
        """
        try:
            _warn_coding_tools()
            log_info(f"Running shell command: {command}")

            # Check for path escapes in command
            path_error = self._check_command(command)
            if path_error:
                return path_error

            effective_timeout = timeout if timeout is not None else self.shell_timeout

            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
                cwd=str(self.base_dir),
            )

            # Combine stdout and stderr
            output = result.stdout
            if result.stderr:
                output += result.stderr

            header = f"Exit code: {result.returncode}\n"

            # Apply truncation
            truncated_output, was_truncated, total_lines = self._truncate_output(output)

            if was_truncated:
                # Save full output to temp file
                tmp = tempfile.NamedTemporaryFile(
                    mode="w",
                    delete=False,
                    suffix=".txt",
                    prefix="coding_tools_",
                )
                tmp.write(output)
                tmp.close()
                self._temp_files.append(tmp.name)
                truncated_output += f"\n[Output truncated: {total_lines} lines total. Full output saved to: {tmp.name}]"

            return header + truncated_output

        except subprocess.TimeoutExpired:
            effective_timeout = timeout if timeout is not None else self.shell_timeout
            return f"Error: Command timed out after {effective_timeout} seconds"
        except Exception as e:
            log_error(f"Error running shell command: {e}")
            return f"Error running shell command: {e}"

    def grep(
        self,
        pattern: str,
        path: Optional[str] = None,
        ignore_case: bool = False,
        include: Optional[str] = None,
        context: int = 0,
        limit: int = 100,
    ) -> str:
        """Search file contents for a pattern.

        Returns matching lines with file paths and line numbers. Respects
        .gitignore when using grep -r. Output is truncated if it exceeds limits.

        :param pattern: Search pattern (regex by default).
        :param path: Directory or file to search in (default: base directory).
        :param ignore_case: Case-insensitive search (default: False).
        :param include: Filter files by glob pattern, e.g. '*.py'.
        :param context: Number of lines to show before and after each match (default: 0).
        :param limit: Maximum number of matches to return (default: 100).
        :return: Matching lines with file paths and line numbers, or an error message.
        """
        try:
            if not pattern:
                return "Error: Pattern cannot be empty"

            # Resolve search path
            if path:
                safe, resolved_path = self._check_path(path, self.base_dir, self.restrict_to_base_dir)
                if not safe:
                    return f"Error: Path '{path}' is outside the allowed base directory"
            else:
                resolved_path = self.base_dir

            if not resolved_path.exists():
                return f"Error: Path not found: {path or '.'}"

            # Build grep command
            cmd = ["grep", "-rn"]
            if ignore_case:
                cmd.append("-i")
            if context > 0:
                cmd.extend(["-C", str(context)])
            if include:
                cmd.extend(["--include", include])

            cmd.append(pattern)
            cmd.append(str(resolved_path))

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(self.base_dir),
            )

            output = result.stdout
            if not output:
                if result.returncode == 1:
                    return f"No matches found for pattern: {pattern}"
                if result.stderr:
                    return f"Error: {result.stderr.strip()}"
                return f"No matches found for pattern: {pattern}"

            # Make paths relative to base_dir
            base_str = str(self.base_dir) + "/"
            output = output.replace(base_str, "")

            # Enforce global match limit
            output_lines = output.split("\n")
            if len(output_lines) > limit:
                output = "\n".join(output_lines[:limit])
                output += f"\n[Results limited to {limit} matches]"

            # Apply truncation
            output, was_truncated, total_lines = self._truncate_output(output)
            if was_truncated:
                output += f"\n[Output truncated: {total_lines} lines total]"

            return output

        except subprocess.TimeoutExpired:
            return "Error: grep timed out after 30 seconds"
        except FileNotFoundError:
            return "Error: grep command not found. Install grep to use this tool."
        except Exception as e:
            log_error(f"Error running grep: {e}")
            return f"Error running grep: {e}"

    def find(self, pattern: str, path: Optional[str] = None, limit: int = 500) -> str:
        """Search for files by glob pattern.

        Returns matching file paths relative to the search directory.

        :param pattern: Glob pattern to match files, e.g. '*.py', '**/*.json'.
        :param path: Directory to search in (default: base directory).
        :param limit: Maximum number of results (default: 500).
        :return: Matching file paths, one per line, or an error message.
        """
        try:
            if not pattern:
                return "Error: Pattern cannot be empty"

            # Resolve search path
            if path:
                safe, resolved_path = self._check_path(path, self.base_dir, self.restrict_to_base_dir)
                if not safe:
                    return f"Error: Path '{path}' is outside the allowed base directory"
            else:
                resolved_path = self.base_dir

            if not resolved_path.exists():
                return f"Error: Path not found: {path or '.'}"

            if not resolved_path.is_dir():
                return f"Error: Not a directory: {path}"

            # Use pathlib glob
            matches = []
            for match in resolved_path.glob(pattern):
                try:
                    rel_path = match.relative_to(self.base_dir)
                    suffix = "/" if match.is_dir() else ""
                    matches.append(str(rel_path) + suffix)
                except ValueError:
                    continue  # Skip paths outside base_dir

                if len(matches) >= limit:
                    break

            if not matches:
                return f"No files found matching pattern: {pattern}"

            result = "\n".join(sorted(matches))

            footer = ""
            if len(matches) >= limit:
                footer = f"\n[Results limited to {limit} entries]"

            return result + footer

        except Exception as e:
            log_error(f"Error finding files: {e}")
            return f"Error finding files: {e}"

    def ls(self, path: Optional[str] = None, limit: int = 500) -> str:
        """List directory contents.

        Returns entries sorted alphabetically with '/' suffix for directories.
        Includes dotfiles.

        :param path: Directory to list (default: base directory).
        :param limit: Maximum number of entries to return (default: 500).
        :return: Directory listing, one entry per line, or an error message.
        """
        try:
            # Resolve path
            if path:
                safe, resolved_path = self._check_path(path, self.base_dir, self.restrict_to_base_dir)
                if not safe:
                    return f"Error: Path '{path}' is outside the allowed base directory"
            else:
                resolved_path = self.base_dir

            if not resolved_path.exists():
                return f"Error: Path not found: {path or '.'}"

            if not resolved_path.is_dir():
                return f"Error: Not a directory: {path}"

            entries = []
            for entry in sorted(resolved_path.iterdir(), key=lambda p: p.name.lower()):
                suffix = "/" if entry.is_dir() else ""
                entries.append(entry.name + suffix)
                if len(entries) >= limit:
                    break

            if not entries:
                return f"Directory is empty: {path or '.'}"

            result = "\n".join(entries)

            if len(entries) >= limit:
                result += f"\n[Listing limited to {limit} entries]"

            return result

        except PermissionError:
            return f"Error: Permission denied: {path or '.'}"
        except Exception as e:
            log_error(f"Error listing directory: {e}")
            return f"Error listing directory: {e}"
