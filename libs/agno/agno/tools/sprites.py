import json
import math
from typing import Dict, List, Optional

from agno.tools import Toolkit

try:
    from sprites import Sprite
    from sprites.exceptions import SpriteError
except ImportError:
    raise ImportError("`sprites-py` not installed. Please install using `pip install 'agno[sprites]'`") from None


class SpritesTools(Toolkit):
    """Run commands in a caller-owned Fly.io Sprite.

    The caller supplies a synchronous ``sprites.Sprite`` and owns its lifecycle.
    This toolkit never creates, stops, or deletes a Sprite, and ``close()`` does
    not close the caller's SDK client. Reuse the same Sprite to retain files and
    installed packages between agent runs. Each command starts a new process;
    shell variables and interpreter memory are not shared between commands.

    ``timeout`` bounds the SDK call, not guaranteed remote process termination.
    A timeout or connection loss leaves execution status unknown; commands are
    never retried automatically. Inspect the Sprite before retrying side effects.

    ``max_output_chars`` limits each returned stream after the SDK captures it;
    it does not limit remote output or SDK buffering. ``cwd`` sets a working
    directory, not a filesystem access boundary.
    """

    def __init__(
        self,
        sprite: Sprite,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: int = 60,
        max_output_chars: int = 16000,
        enable_run_shell_command: bool = True,
        **kwargs,
    ):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive and finite")
        if max_output_chars <= 0:
            raise ValueError("max_output_chars must be positive")

        self.sprite = sprite
        self.cwd = cwd
        self.env = dict(env) if env is not None else None
        self.max_output_chars = max_output_chars

        tools = [self.run_shell_command] if enable_run_shell_command else []
        super().__init__(name="sprites_tools", tools=tools, timeout=timeout, **kwargs)

    def run_shell_command(self, args: List[str]) -> str:
        """Execute a command in the Sprite and return its result as JSON.

        Args:
            args (List[str]): Executable and arguments, passed without shell expansion.
                For shell syntax, explicitly use ["bash", "-lc", "your command"].

        Returns:
            str: JSON with stdout, stderr, exit_code, and per-stream truncation flags.
                On an SDK error, exit_code is null with error and message fields.
                A timeout may leave the remote command running. Files persist across
                calls; each command has its own process and environment.
        """
        if not args:
            raise ValueError("args must contain an executable")

        try:
            result = self.sprite.run(
                *args, capture_output=True, check=False, cwd=self.cwd, env=self.env, timeout=self.timeout
            )
        except TimeoutError:
            return json.dumps(
                {
                    "exit_code": None,
                    "error": "timeout",
                    "message": "The SDK call timed out. The command may still be running; inspect it before retrying.",
                }
            )
        except SpriteError as error:
            return json.dumps(
                {
                    "exit_code": None,
                    "error": type(error).__name__,
                    "message": "The Sprite request failed. Execution status may be unknown; no retry was attempted.",
                }
            )

        stdout = (result.stdout or b"").decode("utf-8", errors="replace")
        stderr = (result.stderr or b"").decode("utf-8", errors="replace")
        return json.dumps(
            {
                "stdout": stdout[: self.max_output_chars],
                "stderr": stderr[: self.max_output_chars],
                "exit_code": result.returncode,
                "stdout_truncated": len(stdout) > self.max_output_chars,
                "stderr_truncated": len(stderr) > self.max_output_chars,
            }
        )
