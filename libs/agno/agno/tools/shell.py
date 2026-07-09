from pathlib import Path
from typing import List, Optional, Union

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_info, log_warning


class ShellTools(Toolkit):
    # A conservative allowlist of read-only / build commands used when
    # restrict_to_base_dir is True and no custom allowlist is supplied.
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

    # Shell operators that enable command chaining / substitution. Because the
    # args list is executed directly (no shell), these only matter if a caller
    # passes them as literal tokens — which a prompt-injected agent may do.
    _DANGEROUS_TOKENS = ("&&", "||", ";", "|", "$(", "`", ">", "<")

    def __init__(
        self,
        base_dir: Optional[Union[Path, str]] = None,
        enable_run_shell_command: bool = True,
        all: bool = False,
        require_confirmation: bool = False,
        restrict_to_base_dir: bool = False,
        allowed_commands: Optional[List[str]] = None,
        **kwargs,
    ):
        """Initialize ShellTools.

        .. warning::
            ``run_shell_command`` executes an arbitrary command on the host OS. By
            default no input validation or sandboxing is applied, which makes this
            tool an RCE sink if the agent is prompt-injected. To harden it, set
            ``require_confirmation=True`` (gates every command behind human
            approval) and/or ``restrict_to_base_dir=True`` with an
            ``allowed_commands`` allowlist.

        Args:
            base_dir: Working directory for executed commands. Only acts as the
                subprocess cwd unless ``restrict_to_base_dir`` is True.
            enable_run_shell_command: Register the ``run_shell_command`` tool.
            all: Register all tools.
            require_confirmation: If True, mark ``run_shell_command`` as requiring
                human-in-the-loop confirmation before execution.
            restrict_to_base_dir: If True, block shell operators, validate the
                command against ``allowed_commands``, and reject path-like tokens
                that resolve outside ``base_dir``.
            allowed_commands: Allowlist of command names (basename) when
                ``restrict_to_base_dir`` is True. Defaults to
                ``DEFAULT_ALLOWED_COMMANDS``. Set to an empty list to allow nothing.
        """
        self.base_dir: Optional[Path] = None
        if base_dir is not None:
            self.base_dir = Path(base_dir) if isinstance(base_dir, str) else base_dir
        if self.base_dir is None:
            self.base_dir = Path.cwd()

        self.restrict_to_base_dir: bool = restrict_to_base_dir
        self.allowed_commands: Optional[List[str]] = (
            allowed_commands if allowed_commands is not None else self.DEFAULT_ALLOWED_COMMANDS
        )

        tools = []
        if all or enable_run_shell_command:
            tools.append(self.run_shell_command)

        super().__init__(
            name="shell_tools",
            tools=tools,
            requires_confirmation_tools=["run_shell_command"] if require_confirmation else None,
            **kwargs,
        )

    def _validate_command(self, args: List[str]) -> Optional[str]:
        """Validate a command list before execution.

        Returns an error message string if the command is unsafe, or None if it
        is allowed to run. No-op when ``restrict_to_base_dir`` is False.
        """
        if not self.restrict_to_base_dir:
            return None

        if not args:
            return "Error: Empty command — nothing to execute."

        # base_dir is always set in __init__ (defaults to cwd); narrow for mypy.
        base_dir = self.base_dir if self.base_dir is not None else Path.cwd()

        # Reject shell operators passed as literal tokens.
        for token in args:
            if token in self._DANGEROUS_TOKENS:
                return f"Error: Shell operator '{token}' is not allowed in restricted mode."

        # Validate the command against the allowlist (basename handles /usr/bin/python).
        command = args[0]
        command_base = Path(command).name
        if self.allowed_commands is not None and command_base not in self.allowed_commands:
            return f"Error: Command '{command_base}' is not in the allowed commands list."

        # Reject path-like tokens that escape base_dir.
        for token in args[1:]:
            if token.startswith("-"):
                continue
            if "/" in token or token == "..":
                try:
                    resolved = Path(token).resolve() if token.startswith("/") else (base_dir / token).resolve()
                    resolved.relative_to(base_dir)
                except ValueError:
                    return f"Error: Command references path outside base directory: {token}"
                except (OSError, RuntimeError):
                    continue

        return None

    def run_shell_command(self, args: List[str], tail: int = 100) -> str:
        """Runs a shell command and returns the output or error.

        .. warning::
            The command is executed directly on the host OS. Harden this tool via
            ``require_confirmation=True`` and/or ``restrict_to_base_dir=True`` on
            ``ShellTools`` to avoid arbitrary code execution.

        Args:
            args (List[str]): The command to run as a list of strings.
            tail (int): The number of lines to return from the output.

        Returns:
            str: The output of the command.
        """
        import subprocess

        try:
            # Input validation at the boundary: args must be a list of strings.
            if not isinstance(args, (list, tuple)):
                return f"Error: args must be a list of strings, got {type(args).__name__}."
            for token in args:
                if not isinstance(token, str):
                    return f"Error: Each command token must be a string, got {type(token).__name__}."

            validation_error = self._validate_command(list(args))
            if validation_error is not None:
                log_warning(f"Blocked shell command: {validation_error}")
                return validation_error

            log_info(f"Running shell command: {args}")
            result = subprocess.run(
                list(args),
                capture_output=True,
                text=True,
                cwd=str(self.base_dir) if self.base_dir else None,
            )
            log_debug(f"Result: {result}")
            log_debug(f"Return code: {result.returncode}")
            if result.returncode != 0:
                return f"Error: {result.stderr}"
            return "\n".join(result.stdout.split("\n")[-tail:])
        except Exception as e:
            log_warning(f"Failed to run shell command: {str(e)}")
            return f"Error: {e}"
