import json
from pathlib import Path
from typing import Callable, List, Optional, Union

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_info, log_warning


class ShellTools(Toolkit):
    # Agno 2.x kwarg names accepted for backwards compatibility
    _legacy_param_aliases = {
        "all": "run_shell_command",
    }

    def __init__(
        self,
        base_dir: Optional[Union[Path, str]] = None,
        run_shell_command: bool = False,
        **kwargs,
    ):
        """Initialize ShellTools.

        Args:
            base_dir: Working directory for commands. Defaults to None (current directory).
            run_shell_command: Enable the run_shell_command tool. Defaults to False
                (executes arbitrary commands on the host).

        .. warning::
            ``run_shell_command`` runs an arbitrary command on the host OS with no
            sandboxing — an RCE sink if the agent is prompt-injected. To require
            human approval before any command executes, gate the tool through the
            toolkit's confirmation mechanism::

                ShellTools(requires_confirmation_tools=["run_shell_command"])
        """
        self.base_dir: Optional[Path] = None
        if base_dir is not None:
            self.base_dir = Path(base_dir) if isinstance(base_dir, str) else base_dir

        tools: List[Callable] = []
        if run_shell_command:
            tools.append(self.run_shell_command)

        super().__init__(name="shell_tools", tools=tools, **kwargs)

    def run_shell_command(self, args: List[str], tail: int = 100) -> str:
        """Runs a shell command and returns the output or error.

        .. warning::
            The command is executed directly on the host OS. Gate this tool with
            ``requires_confirmation_tools=["run_shell_command"]`` to require human
            approval and avoid arbitrary code execution.

        Args:
            args (List[str]): The command to run as a list of strings.
            tail (int): The number of lines to return from the output.

        Returns:
            str: The output of the command.
        """
        import subprocess

        try:
            log_info(f"Running shell command: {args}")
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                cwd=str(self.base_dir) if self.base_dir else None,
            )
            log_debug(f"Result: {result}")
            log_debug(f"Return code: {result.returncode}")
            if result.returncode != 0:
                return json.dumps({"error": result.stderr})
            return "\n".join(result.stdout.split("\n")[-tail:])
        except Exception as e:
            log_warning(f"Failed to run shell command: {str(e)}")
            return json.dumps({"error": str(e)})
