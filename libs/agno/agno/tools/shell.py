from pathlib import Path
from typing import List, Optional, Union

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_info, logger


class ShellTools(Toolkit):
    def __init__(self, base_dir: Optional[Union[Path, str]] = None, **kwargs):
        super().__init__(name="shell_tools", **kwargs)

        self.base_dir: Optional[Path] = None
        if base_dir is not None:
            self.base_dir = Path(base_dir) if isinstance(base_dir, str) else base_dir

        self.register(self.run_shell_command)

    def run_shell_command(self, args: List[str], tail: int = 100) -> str:
        """Runs a shell command and returns the output or error.

        Args:
            args (List[str]): The command to run as a list of strings.
            tail (int): The number of lines to return from the output.
        Returns:
            str: The output of the command.
        """
        import subprocess

        try:
            log_info(f"Running shell command: {args}")
            if self.base_dir:
                args = ["cd", str(self.base_dir), ";"] + args
            result = subprocess.run(args, capture_output=True, text=True)
            log_debug(f"Result: {result}")
            log_debug(f"Return code: {result.returncode}")
            if result.returncode != 0:
                return f"Error: {result.stderr}"
            # return only the last n lines of the output
            return "\n".join(result.stdout.split("\n")[-tail:])
        except Exception as e:
            logger.warning(f"Failed to run shell command: {e}")
            return f"Error: {e}"
