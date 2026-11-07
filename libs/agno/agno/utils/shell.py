import io
from typing import List

from agno.utils.log import log_debug, log_info, log_warning


def run_shell_command(args: List[str], tail: int = 100) -> str:
    log_info(f"Running shell command: {args}")

    import subprocess

    try:
        result = subprocess.run(args, capture_output=True, text=True)
        log_debug(f"Result: {result}")
        log_debug(f"Return code: {result.returncode}")
        if result.returncode != 0:
            return f"Error: {result.stderr}"

        # Split on "\n" only (str.splitlines also breaks on form feed and other
        # separators) and keep line endings so a trailing newline does not count
        # as an extra empty line; tail=0 asks for no lines ([-0:] would return
        # the whole output).
        lines = io.StringIO(result.stdout, newline="\n").readlines()
        return "".join(lines[-tail:]) if tail > 0 else ""
    except Exception as e:
        log_warning(f"Failed to run shell command: {str(e)}")
        return f"Error: {e}"
