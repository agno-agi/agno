import subprocess
from pathlib import Path
from typing import List, Optional, Union

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_info


class GrepTools(Toolkit):
    def __init__(
        self,
        base_dir: Optional[Union[Path, str]] = None,
        enable_grep: bool = True,
        enable_grep_recursive: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.base_dir: Path = Path(base_dir) if isinstance(base_dir, str) else (base_dir or Path.cwd())
        self.base_dir = self.base_dir.resolve()

        tools: List = []
        if all or enable_grep:
            tools.append(self.grep)
        if all or enable_grep_recursive:
            tools.append(self.grep_recursive)

        super().__init__(name="grep_tools", tools=tools, **kwargs)

    def grep(
        self,
        pattern: str,
        file: str,
        ignore_case: bool = False,
        line_numbers: bool = True,
        context_lines: int = 0,
    ) -> str:
        """Search for a pattern in a specific file using grep.

        Args:
            pattern (str): The pattern to search for (supports regex).
            file (str): The file path to search in (relative to base_dir).
            ignore_case (bool): Case insensitive search (default: False).
            line_numbers (bool): Show line numbers (default: True).
            context_lines (int): Number of context lines before and after match (default: 0).

        Returns:
            str: The grep output with matching lines, or error message.
        """
        try:
            # Build grep command
            cmd = ["grep"]

            if ignore_case:
                cmd.append("-i")
            if line_numbers:
                cmd.append("-n")
            if context_lines > 0:
                cmd.extend(["-C", str(context_lines)])

            cmd.append(pattern)
            cmd.append(file)

            log_info(f"Running: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.base_dir),
            )

            log_debug(f"Return code: {result.returncode}")

            # grep returns 1 if no matches found, 2 for errors
            if result.returncode == 1:
                return f"No matches found for pattern '{pattern}' in {file}"
            elif result.returncode == 2:
                return f"Error: {result.stderr}"

            return result.stdout if result.stdout else "No output"

        except FileNotFoundError:
            return "Error: grep command not found. Please ensure grep is installed."
        except Exception as e:
            log_error(f"Error running grep: {e}")
            return f"Error: {e}"

    def grep_recursive(
        self,
        pattern: str,
        file_pattern: str = "*",
        ignore_case: bool = False,
        line_numbers: bool = True,
        context_lines: int = 0,
        max_results: int = 100,
    ) -> str:
        """Recursively search for a pattern in files matching a pattern using grep.

        Args:
            pattern (str): The pattern to search for (supports regex).
            file_pattern (str): File pattern to match, e.g. "*.py", "*.txt" (default: "*").
            ignore_case (bool): Case insensitive search (default: False).
            line_numbers (bool): Show line numbers (default: True).
            context_lines (int): Number of context lines before and after match (default: 0).
            max_results (int): Maximum number of results to return (default: 100).

        Returns:
            str: The grep output with matching lines, or error message.
        """
        try:
            # Build grep command
            cmd = ["grep", "-r"]

            if ignore_case:
                cmd.append("-i")
            if line_numbers:
                cmd.append("-n")
            if context_lines > 0:
                cmd.extend(["-C", str(context_lines)])

            # Add file pattern filter
            cmd.extend(["--include", file_pattern])

            cmd.append(pattern)
            cmd.append(".")

            log_info(f"Running: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.base_dir),
            )

            log_debug(f"Return code: {result.returncode}")

            # grep returns 1 if no matches found, 2 for errors
            if result.returncode == 1:
                return f"No matches found for pattern '{pattern}' in {file_pattern} files"
            elif result.returncode == 2:
                return f"Error: {result.stderr}"

            # Limit results
            output_lines = result.stdout.strip().split("\n")
            if len(output_lines) > max_results:
                output_lines = output_lines[:max_results]
                output_lines.append(f"\n... (truncated to {max_results} results)")

            return "\n".join(output_lines) if output_lines else "No output"

        except FileNotFoundError:
            return "Error: grep command not found. Please ensure grep is installed."
        except Exception as e:
            log_error(f"Error running grep: {e}")
            return f"Error: {e}"
