import json
import os
import subprocess
import sys
from pathlib import Path
from threading import Timer
from typing import Any, List, Optional, Union
from urllib.parse import quote
from uuid import uuid4

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_info, log_warning


class WarpTools(Toolkit):
    """Control the Warp terminal (https://www.warp.dev).

    Uses Warp's desktop integration and optional agent CLI:

    - The ``warp://`` URI scheme to open windows, tabs, tab configs and
      launch configurations in the Warp desktop app.
    - Generated temporary Tab Config TOML files to open a new Warp tab that
      runs a set of startup commands.
    - The ``oz`` CLI (optional) to run Warp agents and capture their output.

    Opening windows, tabs and launch configurations is fire-and-forget: Warp
    does not expose an API to read output back from GUI terminal sessions.
    Use ``run_agent`` (backed by the ``oz`` CLI) when output is needed.
    """

    def __init__(
        self,
        launch_config_dir: Optional[Union[Path, str]] = None,
        enable_open_window: bool = True,
        enable_open_tab: bool = True,
        enable_run_commands: bool = True,
        enable_open_launch_config: bool = True,
        enable_open_tab_config: bool = True,
        enable_run_agent: bool = False,
        all: bool = False,
        tab_config_dir: Optional[Union[Path, str]] = None,
        **kwargs,
    ):
        """Initialize WarpTools.

        Args:
            launch_config_dir: Directory containing saved launch configuration
                files. Defaults to Warp's platform-specific launch
                configurations directory.
            enable_open_window: Enable the open_window tool.
            enable_open_tab: Enable the open_tab tool.
            enable_run_commands: Enable the run_commands tool.
            enable_open_launch_config: Enable the open_launch_config tool.
            enable_open_tab_config: Enable the open_tab_config tool.
            enable_run_agent: Enable the run_agent tool (requires the ``oz``
                CLI to be installed and authenticated).
            all: Enable all tools.
            tab_config_dir: Directory where generated Tab Config files are
                written. Defaults to Warp's platform-specific Tab Config
                directory.

        .. warning::
            ``run_commands`` executes arbitrary commands in a new Warp tab on
            the host OS — an RCE sink if the agent is
            prompt-injected. To require human approval before any command
            executes, gate the tool through the toolkit's confirmation
            mechanism::

                WarpTools(requires_confirmation_tools=["run_commands"])
        """
        self.launch_config_dir: Path = (
            Path(launch_config_dir) if launch_config_dir is not None else self._default_launch_config_dir()
        )
        self.tab_config_dir: Path = (
            Path(tab_config_dir) if tab_config_dir is not None else self._default_tab_config_dir()
        )

        tools: List[Any] = []
        if all or enable_open_window:
            tools.append(self.open_window)
        if all or enable_open_tab:
            tools.append(self.open_tab)
        if all or enable_run_commands:
            tools.append(self.run_commands)
        if all or enable_open_launch_config:
            tools.append(self.open_launch_config)
        if all or enable_open_tab_config:
            tools.append(self.open_tab_config)
        if all or enable_run_agent:
            tools.append(self.run_agent)

        super().__init__(name="warp_tools", tools=tools, **kwargs)

    @staticmethod
    def _default_launch_config_dir() -> Path:
        if sys.platform == "darwin":
            return Path.home() / ".warp" / "launch_configurations"
        if os.name == "nt":
            appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
            return Path(appdata) / "warp" / "Warp" / "data" / "launch_configurations"
        xdg_data_home = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
        return Path(xdg_data_home) / "warp-terminal" / "launch_configurations"

    @staticmethod
    def _default_tab_config_dir() -> Path:
        if sys.platform == "darwin":
            return Path.home() / ".warp" / "tab_configs"
        if os.name == "nt":
            appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
            return Path(appdata) / "warp" / "Warp" / "data" / "tab_configs"
        xdg_data_home = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
        return Path(xdg_data_home) / "warp-terminal" / "tab_configs"

    @staticmethod
    def _open_uri(uri: str) -> Optional[str]:
        """Open a warp:// URI with the OS handler. Returns an error message or None."""
        log_debug(f"Opening Warp URI: {uri}")
        try:
            if os.name == "nt":
                os.startfile(uri)  # type: ignore[attr-defined]
                return None
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            result = subprocess.run([opener, uri], capture_output=True, text=True)
            if result.returncode != 0:
                return f"Error opening Warp URI: {result.stderr.strip() or 'unknown error'}"
            return None
        except Exception as e:
            return f"Error opening Warp URI: {e}"

    def _write_tab_config(self, commands: List[str], cwd: str, title: str, config_name: str) -> Path:
        """Write a Warp Tab Config TOML file and return its path."""
        display_name = title or "Agno"
        config = "\n".join(
            [
                f"name = {json.dumps(display_name, ensure_ascii=False)}",
                f"title = {json.dumps(display_name, ensure_ascii=False)}",
                "",
                "[[panes]]",
                'id = "main"',
                'type = "terminal"',
                f"directory = {json.dumps(cwd, ensure_ascii=False)}",
                f"commands = {json.dumps(commands, ensure_ascii=False)}",
                "is_focused = true",
                "",
            ]
        )
        self.tab_config_dir.mkdir(parents=True, exist_ok=True)
        config_path = self.tab_config_dir / f"{config_name}.toml"
        config_path.write_text(config, encoding="utf-8")
        return config_path

    @staticmethod
    def _schedule_tab_config_cleanup(config_path: Path, delay: float = 30.0) -> None:
        """Remove a generated Tab Config after Warp has had time to open it."""

        def remove_config() -> None:
            try:
                config_path.unlink(missing_ok=True)
            except OSError as e:
                log_warning(f"Failed to remove generated Warp Tab Config {config_path}: {e}")

        cleanup_timer = Timer(delay, remove_config)
        cleanup_timer.daemon = True
        cleanup_timer.start()

    def open_window(self, path: Optional[str] = None) -> str:
        """Opens a new Warp terminal window, optionally at a given directory.

        Args:
            path (Optional[str]): Absolute path of the directory to open the window in.

        Returns:
            str: Confirmation or error message.
        """
        uri = "warp://action/new_window"
        if path:
            uri += f"?path={quote(str(Path(path).expanduser().resolve()))}"
        log_info(f"Opening new Warp window (path={path})")
        error = self._open_uri(uri)
        if error:
            return error
        return f"Opened a new Warp window{f' at {path}' if path else ''}."

    def open_tab(self, path: Optional[str] = None) -> str:
        """Opens a new tab in the active Warp window, optionally at a given directory.

        Args:
            path (Optional[str]): Absolute path of the directory to open the tab in.

        Returns:
            str: Confirmation or error message.
        """
        uri = "warp://action/new_tab"
        if path:
            uri += f"?path={quote(str(Path(path).expanduser().resolve()))}"
        log_info(f"Opening new Warp tab (path={path})")
        error = self._open_uri(uri)
        if error:
            return error
        return f"Opened a new Warp tab{f' at {path}' if path else ''}."

    def run_commands(self, commands: List[str], path: Optional[str] = None, title: str = "Agno") -> str:
        """Opens a new Warp tab and runs the given shell commands in it.

        A temporary Tab Config is removed after Warp has had time to open it.
        The commands run in a visible Warp terminal session. Output is not
        captured — the session stays open for the user to inspect.

        .. warning::
            Commands are executed directly on the host OS. Gate this tool with
            ``requires_confirmation_tools=["run_commands"]`` to require human
            approval and avoid arbitrary code execution.

        Args:
            commands (List[str]): Shell commands to run, in order.
            path (Optional[str]): Working directory for the commands. Defaults to the current directory.
            title (str): Title for the Warp tab.

        Returns:
            str: Confirmation or error message.
        """
        if not commands:
            return "Error: no commands provided."
        cwd = str(Path(path).expanduser().resolve()) if path else str(Path.cwd())
        config_name = f"agno_{uuid4().hex[:8]}"
        try:
            config_path = self._write_tab_config(commands=commands, cwd=cwd, title=title, config_name=config_name)
        except Exception as e:
            log_warning(f"Failed to write Warp Tab Config: {e}")
            return f"Error writing Tab Config: {e}"
        log_info(f"Running {len(commands)} command(s) in a new Warp tab (cwd={cwd})")
        error = self._open_uri(f"warp://tab_config/{quote(config_name)}")
        if error:
            try:
                config_path.unlink(missing_ok=True)
            except OSError as e:
                log_warning(f"Failed to remove unused Warp Tab Config {config_path}: {e}")
            return error
        self._schedule_tab_config_cleanup(config_path)
        return (
            f"Opened a new Warp tab at {cwd} running: {'; '.join(commands)}. "
            f"Temporary Tab Config created at {config_path} and scheduled for cleanup. "
            "Output is shown in the Warp tab and is not captured here."
        )

    def open_launch_config(self, config: str) -> str:
        """Opens a saved Warp launch configuration (windows, tabs and panes).

        Args:
            config (str): Path to a launch configuration YAML file, or the name of
                a configuration in Warp's launch configurations directory.

        Returns:
            str: Confirmation or error message.
        """
        config_path = Path(config).expanduser()
        if not config_path.is_file():
            for candidate in (config, f"{config}.yaml", f"{config}.yml"):
                candidate_path = self.launch_config_dir / candidate
                if candidate_path.is_file():
                    config_path = candidate_path
                    break
            else:
                return f"Error: launch configuration not found: {config} (searched {self.launch_config_dir})"
        log_info(f"Opening Warp launch configuration: {config_path}")
        error = self._open_uri(f"warp://launch/{quote(str(config_path.resolve()), safe='/')}")
        if error:
            return error
        return f"Opened Warp launch configuration: {config_path}"

    def open_tab_config(self, name: str, new_window: bool = False) -> str:
        """Opens a saved Warp Tab Config by name as a new tab.

        Args:
            name (str): Name of the saved Tab Config (case-insensitive).
            new_window (bool): Open the Tab Config in a new window instead of a new tab.

        Returns:
            str: Confirmation or error message.
        """
        uri = f"warp://tab_config/{quote(name)}"
        if new_window:
            uri += "?new_window=true"
        log_info(f"Opening Warp tab config: {name}")
        error = self._open_uri(uri)
        if error:
            return error
        return f"Opened Warp tab config '{name}'{' in a new window' if new_window else ''}."

    def run_agent(
        self,
        prompt: str,
        model: Optional[str] = None,
        path: Optional[str] = None,
        timeout: int = 600,
        tail: int = 200,
    ) -> str:
        """Runs a Warp agent with the given prompt using the ``oz`` CLI and returns its output.

        Requires the ``oz`` CLI to be installed and authenticated
        (``oz login`` or the WARP_API_KEY environment variable).

        .. warning::
            The agent can execute commands on the host OS. Gate this tool with
            ``requires_confirmation_tools=["run_agent"]`` to require human approval.

        Args:
            prompt (str): The task for the Warp agent.
            model (Optional[str]): Model to use (see ``oz model list``).
            path (Optional[str]): Working directory for the agent. Defaults to the current directory.
            timeout (int): Maximum seconds to wait for the agent to finish.
            tail (int): Number of trailing output lines to return.

        Returns:
            str: The agent output, or an error message.
        """
        import shutil

        if shutil.which("oz") is None:
            return (
                "Error: the 'oz' CLI is not installed. Install it with 'brew install --cask oz' "
                "or from https://docs.warp.dev/reference/cli/ and authenticate with 'oz login'."
            )
        args = ["oz", "agent", "run", "--prompt", prompt]
        if model:
            args += ["--model", model]
        cwd = str(Path(path).expanduser().resolve()) if path else None
        log_info(f"Running Warp agent via oz (model={model}, cwd={cwd})")
        try:
            result = subprocess.run(args, capture_output=True, text=True, cwd=cwd, timeout=timeout)
        except subprocess.TimeoutExpired:
            return f"Error: Warp agent run timed out after {timeout} seconds."
        except Exception as e:
            log_warning(f"Failed to run Warp agent: {e}")
            return f"Error running Warp agent: {e}"
        if result.returncode != 0:
            return f"Error: {result.stderr.strip() or result.stdout.strip()}"
        return "\n".join(result.stdout.splitlines()[-tail:])
