from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional

from agno.skills.utils import ScriptResult, run_script


class SkillExecutor(ABC):
    """Abstract base class for skill script executors.

    Skill executors are responsible for running a skill's script and reporting what it produced.
    Subclasses must implement the `run()` method to define where and how the script runs.
    """

    @abstractmethod
    def run(
        self,
        script_path: Path,
        *,
        args: Optional[List[str]] = None,
        timeout: int = 30,
        cwd: Optional[Path] = None,
    ) -> ScriptResult:
        """Run a script and return the result.

        Args:
            script_path: Path to the script to run.
            args: Optional list of arguments to pass to the script.
            timeout: Maximum execution time in seconds.
            cwd: Working directory for the script.

        Returns:
            ScriptResult with stdout, stderr, and returncode.

        Raises:
            subprocess.TimeoutExpired: If the script exceeds timeout.
            FileNotFoundError: If the script or its interpreter is not found.
        """
        pass


class LocalSkillExecutor(SkillExecutor):
    """Runs a skill's script as a subprocess on the host, with the privileges of this process."""

    def run(
        self,
        script_path: Path,
        *,
        args: Optional[List[str]] = None,
        timeout: int = 30,
        cwd: Optional[Path] = None,
    ) -> ScriptResult:
        """Run a script on the local host.

        Args:
            script_path: Path to the script to run.
            args: Optional list of arguments to pass to the script.
            timeout: Maximum execution time in seconds.
            cwd: Working directory for the script.

        Returns:
            ScriptResult with stdout, stderr, and returncode.

        Raises:
            subprocess.TimeoutExpired: If the script exceeds timeout.
            FileNotFoundError: If the script or its interpreter is not found.
        """
        return run_script(script_path=script_path, args=args, timeout=timeout, cwd=cwd)
