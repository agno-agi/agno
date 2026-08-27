"""Unit tests for WarpTools class."""

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agno.tools.warp import WarpTools


@pytest.fixture
def warp_tools(tmp_path):
    """Create a WarpTools instance with all tools enabled and an isolated config dir."""
    return WarpTools(
        all=True,
        launch_config_dir=tmp_path / "launch_configurations",
        tab_config_dir=tmp_path / "tab_configs",
    )


# ---------------------------------------------------------------------------
# Initialization and tool registration
# ---------------------------------------------------------------------------


def test_initialization_default_tools():
    """Default initialization registers URI tools but not run_agent."""
    tools = WarpTools()
    function_names = [func.name for func in tools.functions.values()]

    assert "open_window" in function_names
    assert "open_tab" in function_names
    assert "run_commands" in function_names
    assert "open_launch_config" in function_names
    assert "open_tab_config" in function_names
    assert "run_agent" not in function_names


def test_initialization_with_all_tools():
    """all=True registers every tool, including run_agent."""
    tools = WarpTools(all=True)
    function_names = [func.name for func in tools.functions.values()]

    assert "run_agent" in function_names
    assert len(function_names) == 6


def test_initialization_with_run_agent_enabled():
    """enable_run_agent=True registers run_agent."""
    tools = WarpTools(enable_run_agent=True)
    function_names = [func.name for func in tools.functions.values()]

    assert "run_agent" in function_names


def test_initialization_with_selective_tools():
    """Disabled tools are not registered."""
    tools = WarpTools(
        enable_open_window=False,
        enable_open_tab=False,
        enable_open_launch_config=False,
        enable_open_tab_config=False,
    )
    function_names = [func.name for func in tools.functions.values()]

    assert function_names == ["run_commands"]


def test_initialization_custom_launch_config_dir(tmp_path):
    """A custom launch_config_dir is stored as a Path."""
    tools = WarpTools(launch_config_dir=str(tmp_path))

    assert tools.launch_config_dir == tmp_path


def test_initialization_custom_tab_config_dir(tmp_path):
    """A custom tab_config_dir is stored as a Path."""
    tools = WarpTools(tab_config_dir=str(tmp_path))

    assert tools.tab_config_dir == tmp_path


# ---------------------------------------------------------------------------
# Default launch configuration directory
# ---------------------------------------------------------------------------


def test_default_launch_config_dir_macos():
    with patch("agno.tools.warp.sys.platform", "darwin"):
        assert WarpTools._default_launch_config_dir() == Path.home() / ".warp" / "launch_configurations"


def test_default_launch_config_dir_linux(monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", "/custom/data")
    with patch("agno.tools.warp.sys.platform", "linux"), patch("agno.tools.warp.os.name", "posix"):
        assert WarpTools._default_launch_config_dir() == Path("/custom/data/warp-terminal/launch_configurations")


def test_default_launch_config_dir_linux_without_xdg(monkeypatch):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    with patch("agno.tools.warp.sys.platform", "linux"), patch("agno.tools.warp.os.name", "posix"):
        assert (
            WarpTools._default_launch_config_dir()
            == Path.home() / ".local" / "share" / "warp-terminal" / "launch_configurations"
        )


@pytest.mark.skipif(os.name != "nt", reason="WindowsPath cannot be built on posix systems")
def test_default_launch_config_dir_windows(monkeypatch):
    monkeypatch.setenv("APPDATA", "C:\\appdata")
    assert WarpTools._default_launch_config_dir() == Path("C:\\appdata/warp/Warp/data/launch_configurations")


# ---------------------------------------------------------------------------
# Default Tab Config directory
# ---------------------------------------------------------------------------


def test_default_tab_config_dir_macos():
    with patch("agno.tools.warp.sys.platform", "darwin"):
        assert WarpTools._default_tab_config_dir() == Path.home() / ".warp" / "tab_configs"


def test_default_tab_config_dir_linux(monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", "/custom/data")
    with patch("agno.tools.warp.sys.platform", "linux"), patch("agno.tools.warp.os.name", "posix"):
        assert WarpTools._default_tab_config_dir() == Path("/custom/data/warp-terminal/tab_configs")


def test_default_tab_config_dir_linux_without_xdg(monkeypatch):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    with patch("agno.tools.warp.sys.platform", "linux"), patch("agno.tools.warp.os.name", "posix"):
        assert WarpTools._default_tab_config_dir() == Path.home() / ".local" / "share" / "warp-terminal" / "tab_configs"


@pytest.mark.skipif(os.name != "nt", reason="WindowsPath cannot be built on posix systems")
def test_default_tab_config_dir_windows(monkeypatch):
    monkeypatch.setenv("APPDATA", "C:\\appdata")
    assert WarpTools._default_tab_config_dir() == Path("C:\\appdata/warp/Warp/data/tab_configs")


# ---------------------------------------------------------------------------
# _open_uri
# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.name == "nt", reason="posix opener path")
def test_open_uri_success():
    with patch("agno.tools.warp.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert WarpTools._open_uri("warp://action/new_window") is None

    opener_args = mock_run.call_args[0][0]
    assert opener_args[0] in ("open", "xdg-open")
    assert opener_args[1] == "warp://action/new_window"


@pytest.mark.skipif(os.name == "nt", reason="posix opener path")
def test_open_uri_failure_returns_error():
    with patch("agno.tools.warp.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="no handler")
        result = WarpTools._open_uri("warp://action/new_window")

    assert result is not None
    assert "no handler" in result


@pytest.mark.skipif(os.name == "nt", reason="posix opener path")
def test_open_uri_exception_returns_error():
    with patch("agno.tools.warp.subprocess.run", side_effect=OSError("opener missing")):
        result = WarpTools._open_uri("warp://action/new_window")

    assert result is not None
    assert "opener missing" in result


# ---------------------------------------------------------------------------
# open_window and open_tab
# ---------------------------------------------------------------------------


def test_open_window_without_path(warp_tools):
    with patch.object(WarpTools, "_open_uri", return_value=None) as mock_open:
        result = warp_tools.open_window()

    mock_open.assert_called_once_with("warp://action/new_window")
    assert "Opened a new Warp window" in result


def test_open_window_with_path(warp_tools, tmp_path):
    with patch.object(WarpTools, "_open_uri", return_value=None) as mock_open:
        result = warp_tools.open_window(path=str(tmp_path))

    uri = mock_open.call_args[0][0]
    assert uri.startswith("warp://action/new_window?path=")
    assert str(tmp_path.name) in uri
    assert str(tmp_path) in result


def test_open_window_propagates_error(warp_tools):
    with patch.object(WarpTools, "_open_uri", return_value="Error opening Warp URI: boom"):
        result = warp_tools.open_window()

    assert result == "Error opening Warp URI: boom"


def test_open_tab_without_path(warp_tools):
    with patch.object(WarpTools, "_open_uri", return_value=None) as mock_open:
        result = warp_tools.open_tab()

    mock_open.assert_called_once_with("warp://action/new_tab")
    assert "Opened a new Warp tab" in result


def test_open_tab_with_path_is_url_encoded(warp_tools, tmp_path):
    path_with_space = tmp_path / "my dir"
    path_with_space.mkdir()
    with patch.object(WarpTools, "_open_uri", return_value=None) as mock_open:
        warp_tools.open_tab(path=str(path_with_space))

    uri = mock_open.call_args[0][0]
    assert "my%20dir" in uri
    assert " " not in uri


# ---------------------------------------------------------------------------
# run_commands
# ---------------------------------------------------------------------------


def test_run_commands_writes_tab_config_and_opens_it(warp_tools, tmp_path):
    with patch.object(WarpTools, "_open_uri", return_value=None) as mock_open:
        with patch.object(WarpTools, "_schedule_tab_config_cleanup") as mock_cleanup:
            result = warp_tools.run_commands(commands=["echo hello", "ls -la"], path=str(tmp_path), title="My Tab")

    config_files = list(warp_tools.tab_config_dir.glob("agno_*.toml"))
    assert len(config_files) == 1

    config = config_files[0].read_text(encoding="utf-8")
    assert 'name = "My Tab"' in config
    assert 'title = "My Tab"' in config
    assert "[[panes]]" in config
    assert 'id = "main"' in config
    assert 'type = "terminal"' in config
    assert f"directory = {json.dumps(str(tmp_path.resolve()))}" in config
    assert f"commands = {json.dumps(['echo hello', 'ls -la'])}" in config
    assert "is_focused = true" in config

    uri = mock_open.call_args[0][0]
    assert uri == f"warp://tab_config/{config_files[0].stem}"
    mock_cleanup.assert_called_once_with(config_files[0])

    assert "echo hello" in result
    assert str(config_files[0]) in result
    assert "new Warp tab" in result


def test_run_commands_defaults_to_current_directory(warp_tools):
    with patch.object(WarpTools, "_open_uri", return_value=None):
        with patch.object(WarpTools, "_schedule_tab_config_cleanup"):
            warp_tools.run_commands(commands=["echo hello"])

    config_files = list(warp_tools.tab_config_dir.glob("agno_*.toml"))
    config = config_files[0].read_text(encoding="utf-8")
    assert f"directory = {json.dumps(str(Path.cwd()))}" in config


def test_run_commands_escapes_tab_config_values(warp_tools, tmp_path):
    commands = ['printf "hello\\world"', "echo café"]
    title = 'Agno "Dev"'
    with patch.object(WarpTools, "_open_uri", return_value=None):
        with patch.object(WarpTools, "_schedule_tab_config_cleanup"):
            warp_tools.run_commands(commands=commands, path=str(tmp_path), title=title)

    config_files = list(warp_tools.tab_config_dir.glob("agno_*.toml"))
    config = config_files[0].read_text(encoding="utf-8")
    assert f"name = {json.dumps(title, ensure_ascii=False)}" in config
    assert f"directory = {json.dumps(str(tmp_path.resolve()), ensure_ascii=False)}" in config
    assert f"commands = {json.dumps(commands, ensure_ascii=False)}" in config


def test_write_tab_config_produces_valid_toml(warp_tools, tmp_path):
    tomllib = pytest.importorskip("tomllib")
    config_path = warp_tools._write_tab_config(
        commands=["echo hello", "ls -la"],
        cwd=str(tmp_path),
        title="My Tab",
        config_name="valid_config",
    )

    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert config == {
        "name": "My Tab",
        "title": "My Tab",
        "panes": [
            {
                "id": "main",
                "type": "terminal",
                "directory": str(tmp_path),
                "commands": ["echo hello", "ls -la"],
                "is_focused": True,
            }
        ],
    }


def test_schedule_tab_config_cleanup_removes_file(tmp_path):
    config_path = tmp_path / "generated.toml"
    config_path.write_text('name = "generated"', encoding="utf-8")
    with patch("agno.tools.warp.Timer") as mock_timer:
        WarpTools._schedule_tab_config_cleanup(config_path, delay=5.0)

    cleanup_callback = mock_timer.call_args.args[1]
    cleanup_callback()
    assert not config_path.exists()
    assert mock_timer.call_args.args[0] == 5.0
    assert mock_timer.return_value.daemon is True
    mock_timer.return_value.start.assert_called_once_with()


def test_run_commands_without_commands_returns_error(warp_tools):
    result = warp_tools.run_commands(commands=[])

    assert result == "Error: no commands provided."


def test_run_commands_write_failure_returns_error(warp_tools):
    with patch.object(WarpTools, "_write_tab_config", side_effect=OSError("disk full")):
        result = warp_tools.run_commands(commands=["echo hello"])

    assert "Error writing Tab Config" in result
    assert "disk full" in result


def test_run_commands_propagates_open_error(warp_tools):
    with patch.object(WarpTools, "_open_uri", return_value="Error opening Warp URI: boom"):
        result = warp_tools.run_commands(commands=["echo hello"])

    assert result == "Error opening Warp URI: boom"
    assert list(warp_tools.tab_config_dir.glob("agno_*.toml")) == []


# ---------------------------------------------------------------------------
# open_launch_config
# ---------------------------------------------------------------------------


def test_open_launch_config_with_full_path(warp_tools, tmp_path):
    config_path = tmp_path / "dev.yaml"
    config_path.write_text("name: dev")
    with patch.object(WarpTools, "_open_uri", return_value=None) as mock_open:
        result = warp_tools.open_launch_config(str(config_path))

    uri = mock_open.call_args[0][0]
    assert uri.startswith("warp://launch/")
    assert "dev.yaml" in uri
    assert "dev.yaml" in result


def test_open_launch_config_resolves_name_in_config_dir(warp_tools):
    warp_tools.launch_config_dir.mkdir(parents=True)
    (warp_tools.launch_config_dir / "myconf.yaml").write_text("name: myconf")
    with patch.object(WarpTools, "_open_uri", return_value=None) as mock_open:
        result = warp_tools.open_launch_config("myconf")

    assert "myconf.yaml" in mock_open.call_args[0][0]
    assert "Error" not in result


def test_open_launch_config_missing_returns_error(warp_tools):
    result = warp_tools.open_launch_config("does_not_exist")

    assert "Error: launch configuration not found" in result
    assert str(warp_tools.launch_config_dir) in result


# ---------------------------------------------------------------------------
# open_tab_config
# ---------------------------------------------------------------------------


def test_open_tab_config(warp_tools):
    with patch.object(WarpTools, "_open_uri", return_value=None) as mock_open:
        result = warp_tools.open_tab_config("my_tab")

    mock_open.assert_called_once_with("warp://tab_config/my_tab")
    assert "my_tab" in result


def test_open_tab_config_in_new_window(warp_tools):
    with patch.object(WarpTools, "_open_uri", return_value=None) as mock_open:
        result = warp_tools.open_tab_config("my_tab", new_window=True)

    mock_open.assert_called_once_with("warp://tab_config/my_tab?new_window=true")
    assert "new window" in result


def test_open_tab_config_name_is_url_encoded(warp_tools):
    with patch.object(WarpTools, "_open_uri", return_value=None) as mock_open:
        warp_tools.open_tab_config("my tab")

    assert mock_open.call_args[0][0] == "warp://tab_config/my%20tab"


# ---------------------------------------------------------------------------
# run_agent
# ---------------------------------------------------------------------------


def test_run_agent_without_oz_returns_error(warp_tools):
    with patch("shutil.which", return_value=None):
        result = warp_tools.run_agent("do something")

    assert "'oz' CLI is not installed" in result


def test_run_agent_success(warp_tools, tmp_path):
    with patch("shutil.which", return_value="/usr/local/bin/oz"):
        with patch("agno.tools.warp.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="line one\nline two\n", stderr="")
            result = warp_tools.run_agent("fix the tests", model="auto", path=str(tmp_path))

    args, kwargs = mock_run.call_args
    assert args[0] == ["oz", "agent", "run", "--prompt", "fix the tests", "--model", "auto"]
    assert kwargs["cwd"] == str(tmp_path.resolve())
    assert result == "line one\nline two"


def test_run_agent_tail_limits_output(warp_tools):
    stdout = "\n".join(f"line {i}" for i in range(10))
    with patch("shutil.which", return_value="/usr/local/bin/oz"):
        with patch("agno.tools.warp.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=stdout, stderr="")
            result = warp_tools.run_agent("task", tail=3)

    assert result == "line 7\nline 8\nline 9"


def test_run_agent_failure_returns_stderr(warp_tools):
    with patch("shutil.which", return_value="/usr/local/bin/oz"):
        with patch("agno.tools.warp.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not authenticated")
            result = warp_tools.run_agent("task")

    assert result == "Error: not authenticated"


def test_run_agent_timeout_returns_error(warp_tools):
    with patch("shutil.which", return_value="/usr/local/bin/oz"):
        with patch(
            "agno.tools.warp.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="oz", timeout=5),
        ):
            result = warp_tools.run_agent("task", timeout=5)

    assert "timed out after 5 seconds" in result
