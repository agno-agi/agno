import json
import platform
from pathlib import Path
from typing import List, Optional, Set, Union

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_info, logger

# Default dangerous commands to block
DEFAULT_BLACKLIST = {
    "rm -rf /",
    "rm -rf *",
    "format",
    "del /f /s /q",
    "mkfs",
    "dd if=/dev/zero",
    "> /dev/sda",
    "mv /* /dev/null",
    "chmod -R 777 /",
}


class ShellTools(Toolkit):
    def __init__(
        self,
        base_dir: Optional[Union[Path, str]] = None,
        enable_blacklist: bool = False,
        blacklist: Optional[Set[str]] = None,
        timeout: int = 30,
        enable_run_shell_command: bool = True,
        enable_change_directory: bool = True,
        enable_get_current_directory: bool = True,
        enable_list_files: bool = True,
        enable_get_os_info: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """Initialize ShellTools.

        Args:
            base_dir: Base directory for shell operations (default: current directory)
            enable_blacklist: Enable command blacklist for safety (default: False)
            blacklist: Custom set of blacklisted commands (defaults to DEFAULT_BLACKLIST if enable_blacklist=True)
            timeout: Command execution timeout in seconds (default: 30)
            enable_run_shell_command: Enable the run_shell_command tool
            enable_change_directory: Enable the change_directory tool
            enable_get_current_directory: Enable the get_current_directory tool
            enable_list_files: Enable the list_files tool
            enable_get_os_info: Enable the get_os_info tool
            all: Enable all tools (overrides individual enable flags)
            **kwargs: Additional arguments passed to Toolkit
        """
        self.base_dir: Path = Path(base_dir) if base_dir else Path.cwd()
        self.current_dir: Path = self.base_dir
        self.enable_blacklist: bool = enable_blacklist
        self.blacklist: Set[str] = blacklist if blacklist is not None else DEFAULT_BLACKLIST
        self.timeout: int = timeout
        self.os_type: str = platform.system()

        tools: List = []
        if all or enable_run_shell_command:
            tools.append(self.run_shell_command)  # type: ignore

        if all or enable_change_directory:
            tools.append(self.change_directory)  # type: ignore

        if all or enable_get_current_directory:
            tools.append(self.get_current_directory)  # type: ignore

        if all or enable_list_files:
            tools.append(self.list_files)  # type: ignore

        if all or enable_get_os_info:
            tools.append(self.get_os_info)  # type: ignore

        super().__init__(name="shell_tools", tools=tools, **kwargs)

    def _is_command_blacklisted(self, command: Union[str, List[str]]) -> bool:
        """Check if a command is blacklisted.

        Args:
            command: Command string or list to check

        Returns:
            bool: True if command is blacklisted
        """
        if not self.enable_blacklist:
            return False

        cmd_str = " ".join(command) if isinstance(command, list) else command
        cmd_str = cmd_str.lower().strip()

        for blocked in self.blacklist:
            if blocked.lower() in cmd_str:
                return True
        return False

    def run_shell_command(self, args: List[str], tail: int = 100, timeout: Optional[int] = None) -> str:
        """Runs a shell command and returns the output or error.

        Args:
            args (List[str]): The command to run as a list of strings.
            tail (int): The number of lines to return from the output.
            timeout (int, optional): Command timeout in seconds (overrides default).

        Returns:
            str: JSON formatted result with stdout, stderr, return_code, and execution info.
        """
        import subprocess

        try:
            # Check blacklist
            if self._is_command_blacklisted(args):
                error_msg = f"Command blocked by blacklist: {' '.join(args)}"
                logger.warning(error_msg)
                return json.dumps(
                    {
                        "success": False,
                        "error": error_msg,
                        "blocked": True,
                        "command": " ".join(args),
                    },
                    indent=2,
                )

            cmd_timeout = timeout if timeout is not None else self.timeout
            log_info(f"Running shell command: {args} (timeout: {cmd_timeout}s, cwd: {self.current_dir})")

            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                cwd=str(self.current_dir),
                timeout=cmd_timeout,
            )

            log_debug(f"Return code: {result.returncode}")

            # Get tailed output
            stdout_lines = result.stdout.split("\n") if result.stdout else []
            stderr_lines = result.stderr.split("\n") if result.stderr else []

            output = {
                "success": result.returncode == 0,
                "return_code": result.returncode,
                "stdout": "\n".join(stdout_lines[-tail:]) if stdout_lines else "",
                "stderr": "\n".join(stderr_lines[-tail:]) if stderr_lines else "",
                "command": " ".join(args),
                "cwd": str(self.current_dir),
                "os": self.os_type,
            }

            return json.dumps(output, indent=2)

        except subprocess.TimeoutExpired:
            error_msg = f"Command timed out after {cmd_timeout} seconds"
            logger.warning(f"{error_msg}: {args}")
            return json.dumps(
                {
                    "success": False,
                    "error": error_msg,
                    "timeout": True,
                    "command": " ".join(args),
                },
                indent=2,
            )
        except FileNotFoundError as e:
            error_msg = f"Command not found: {args[0]}"
            logger.warning(f"{error_msg}: {e}")
            return json.dumps(
                {
                    "success": False,
                    "error": error_msg,
                    "command": " ".join(args),
                },
                indent=2,
            )
        except Exception as e:
            logger.warning(f"Failed to run shell command: {e}")
            return json.dumps(
                {
                    "success": False,
                    "error": str(e),
                    "command": " ".join(args),
                },
                indent=2,
            )

    def change_directory(self, path: str) -> str:
        """Changes the current working directory.

        Args:
            path (str): Path to change to (absolute or relative to current directory).

        Returns:
            str: JSON formatted result with new current directory.
        """
        try:
            new_path = Path(path)
            if not new_path.is_absolute():
                new_path = self.current_dir / new_path

            new_path = new_path.resolve()

            if not new_path.exists():
                return json.dumps(
                    {
                        "success": False,
                        "error": f"Directory does not exist: {new_path}",
                        "current_directory": str(self.current_dir),
                    },
                    indent=2,
                )

            if not new_path.is_dir():
                return json.dumps(
                    {
                        "success": False,
                        "error": f"Path is not a directory: {new_path}",
                        "current_directory": str(self.current_dir),
                    },
                    indent=2,
                )

            self.current_dir = new_path
            log_info(f"Changed directory to: {self.current_dir}")

            return json.dumps(
                {
                    "success": True,
                    "current_directory": str(self.current_dir),
                    "message": f"Changed to directory: {self.current_dir}",
                },
                indent=2,
            )

        except Exception as e:
            logger.warning(f"Failed to change directory: {e}")
            return json.dumps(
                {
                    "success": False,
                    "error": str(e),
                    "current_directory": str(self.current_dir),
                },
                indent=2,
            )

    def get_current_directory(self) -> str:
        """Gets the current working directory.

        Returns:
            str: JSON formatted result with current directory path.
        """
        return json.dumps(
            {
                "current_directory": str(self.current_dir),
                "absolute_path": str(self.current_dir.absolute()),
            },
            indent=2,
        )

    def list_files(self, path: Optional[str] = None, pattern: str = "*") -> str:
        """Lists files in a directory.

        Args:
            path (str, optional): Directory to list (defaults to current directory).
            pattern (str): Glob pattern to filter files (default: "*").

        Returns:
            str: JSON formatted list of files and directories.
        """
        try:
            target_path = self.current_dir
            if path:
                target_path = Path(path)
                if not target_path.is_absolute():
                    target_path = self.current_dir / target_path
                target_path = target_path.resolve()

            if not target_path.exists():
                return json.dumps(
                    {
                        "success": False,
                        "error": f"Directory does not exist: {target_path}",
                    },
                    indent=2,
                )

            if not target_path.is_dir():
                return json.dumps(
                    {
                        "success": False,
                        "error": f"Path is not a directory: {target_path}",
                    },
                    indent=2,
                )

            items = list(target_path.glob(pattern))
            files = []
            directories = []

            for item in items:
                item_info = {
                    "name": item.name,
                    "path": str(item),
                    "size": item.stat().st_size if item.is_file() else None,
                }
                if item.is_file():
                    files.append(item_info)
                elif item.is_dir():
                    directories.append(item_info)

            return json.dumps(
                {
                    "success": True,
                    "directory": str(target_path),
                    "pattern": pattern,
                    "files": files,
                    "directories": directories,
                    "total_files": len(files),
                    "total_directories": len(directories),
                },
                indent=2,
            )

        except Exception as e:
            logger.warning(f"Failed to list files: {e}")
            return json.dumps(
                {
                    "success": False,
                    "error": str(e),
                },
                indent=2,
            )

    def get_os_info(self) -> str:
        """Gets information about the operating system.

        Returns:
            str: JSON formatted OS information.
        """
        try:
            info = {
                "os": self.os_type,
                "platform": platform.platform(),
                "version": platform.version(),
                "architecture": platform.machine(),
                "processor": platform.processor(),
                "python_version": platform.python_version(),
                "hostname": platform.node(),
            }

            # Add OS-specific info
            if self.os_type == "Windows":
                info["windows_version"] = platform.win32_ver()[0]
            elif self.os_type == "Linux":
                try:
                    if hasattr(platform, "freedesktop_os_release"):
                        info["linux_distribution"] = platform.freedesktop_os_release().get("PRETTY_NAME", "Unknown")  # type: ignore
                    else:
                        info["linux_distribution"] = "Unknown"
                except Exception:
                    info["linux_distribution"] = "Unknown"
            elif self.os_type == "Darwin":
                info["mac_version"] = platform.mac_ver()[0]

            return json.dumps(info, indent=2)

        except Exception as e:
            logger.warning(f"Failed to get OS info: {e}")
            return json.dumps(
                {
                    "success": False,
                    "error": str(e),
                },
                indent=2,
            )
