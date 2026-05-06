import subprocess
from pathlib import Path
from typing import FrozenSet, Iterable, List, Optional, Union

from agno.tools import Toolkit
from agno.tools._security import sanitize_shell_arg
from agno.utils.log import log_debug, log_info, log_warning


class ShellTools(Toolkit):
    """Run shell commands with strict allow-listing.

    Security notes (hardened build):

    * ``allowed_commands`` defaults to an empty set — no commands are
      permitted until the operator explicitly opts into a subset of
      executable basenames, for example ``["ls", "cat", "grep"]``.
    * Setting ``allow_any_command=True`` opts out of the allowlist
      entirely and is intended only for trusted internal deployments.
    * Every argument is validated with
      :func:`agno.tools._security.sanitize_shell_arg` and rejected if
      it contains shell metacharacters, even though ``subprocess.run``
      is always invoked with ``shell=False``.
    * A mandatory timeout (default 30 seconds) bounds each command.
      Callers may pass a smaller value per call; the configured
      default acts as an upper bound.

    Args:
        base_dir: Working directory for spawned processes. The
            process still inherits the parent's environment.
        enable_run_shell_command: When True (default), register
            ``run_shell_command`` as an agent tool.
        allowed_commands: Iterable of permitted executable basenames.
            Empty by default.
        allow_any_command: Opt out of the allowlist. Defaults to
            False.
        default_timeout_seconds: Upper bound on per-command wall-clock
            time. Must be at least 1; defaults to 30.
    """

    def __init__(
        self,
        base_dir: Optional[Union[Path, str]] = None,
        enable_run_shell_command: bool = True,
        allowed_commands: Optional[Iterable[str]] = None,
        allow_any_command: bool = False,
        default_timeout_seconds: int = 30,
        all: bool = False,
        **kwargs,
    ):
        self.base_dir: Optional[Path] = Path(base_dir) if isinstance(base_dir, str) else base_dir

        self._allowed_commands: FrozenSet[str] = (
            frozenset(c.strip() for c in allowed_commands) if allowed_commands is not None else frozenset()
        )
        self._allow_any_command: bool = bool(allow_any_command)
        self._default_timeout_seconds: int = max(1, int(default_timeout_seconds))

        tools: List = []
        if all or enable_run_shell_command:
            tools.append(self.run_shell_command)

        super().__init__(name="shell_tools", tools=tools, **kwargs)

    def _validate_args(self, args: List[str]) -> Optional[str]:
        """Return a reason string if ``args`` should be refused.

        Args:
            args: The command and its arguments as a list of strings.

        Returns:
            None when the command is allowed. Otherwise a short
            explanation suitable for surfacing to the agent.
        """
        if not isinstance(args, list) or not args:
            return "args must be a non-empty list of strings."
        if not all(isinstance(a, str) for a in args):
            return "All shell args must be strings."
        try:
            for a in args:
                sanitize_shell_arg(a)
        except ValueError as e:
            return str(e)
        cmd = Path(args[0]).name
        if not self._allow_any_command and cmd not in self._allowed_commands:
            return (
                f"Command '{cmd}' is not in the allowlist. Configure "
                "ShellTools(allowed_commands=[...]) or pass "
                "allow_any_command=True."
            )
        return None

    def run_shell_command(
        self,
        args: List[str],
        tail: int = 100,
        timeout_seconds: Optional[int] = None,
    ) -> str:
        """Run a shell command and return its stdout tail.

        :param args: The command to run as a list of strings.
        :param tail: Number of trailing stdout lines to return.
        :param timeout_seconds: Optional per-call timeout override.
            Capped at ``default_timeout_seconds``.
        :return: The last ``tail`` lines of stdout on success, or an
            error string.
        """
        err = self._validate_args(args)
        if err:
            log_warning(f"ShellTools rejected command: {err}")
            return f"Error: {err}"

        requested = int(timeout_seconds) if timeout_seconds is not None else self._default_timeout_seconds
        timeout = min(self._default_timeout_seconds, max(1, requested))
        try:
            log_info(f"Running shell command: {args} (timeout={timeout}s)")
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                cwd=str(self.base_dir) if self.base_dir else None,
                shell=False,
                timeout=timeout,
            )
            log_debug(f"Return code: {result.returncode}")
            if result.returncode != 0:
                return f"Error: {result.stderr}"
            return "\n".join(result.stdout.split("\n")[-tail:])
        except subprocess.TimeoutExpired:
            log_warning(f"Shell command timed out after {timeout}s: {args}")
            return f"Error: command timed out after {timeout} seconds"
        except Exception as e:
            log_warning(f"Failed to run shell command: {str(e)}")
            return f"Error: {e}"
