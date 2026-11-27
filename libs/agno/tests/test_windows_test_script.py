"""Exercise the Windows test wrappers with a real pytest executable."""

import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows batch scripts require cmd.exe")

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("entry", ["root", "library", "nested-call"])
@pytest.mark.parametrize("initial_exit_code", [0, 7])
@pytest.mark.parametrize("pytest_exit_code", [0, 1, 5])
def test_windows_test_script_preserves_pytest_exit_code(
    tmp_path: Path, entry: str, initial_exit_code: int, pytest_exit_code: int
) -> None:
    for relative in ("scripts/test.bat", "libs/agno/scripts/test.bat"):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / relative, destination)

    tests = tmp_path / "libs/agno/tests/unit"
    tests.mkdir(parents=True)
    # The library wrapper enables coverage for agno; use an isolated toy module
    # instead of importing the actual framework and its optional dependencies.
    (tests / "agno.py").write_text("VALUE = 1\n", encoding="utf-8")
    if pytest_exit_code != 5:
        assertion = "agno.VALUE == 1" if pytest_exit_code == 0 else "agno.VALUE == 2"
        (tests / "test_sample.py").write_text(
            "import agno\n\ndef test_sample():\n    assert " + assertion + "\n", encoding="utf-8"
        )

    scripts_dir = sysconfig.get_path("scripts")
    assert (Path(scripts_dir) / "pytest.exe").is_file(), "Install pytest in the test interpreter's environment"
    env = os.environ.copy()
    env["PATH"] = scripts_dir + os.pathsep + env.get("PATH", "")
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["PYTEST_PLUGINS"] = "pytest_cov.plugin"
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("PYTEST_CURRENT_TEST", None)

    script = r"libs\agno\scripts\test.bat" if entry == "library" else r"scripts\test.bat"
    if entry == "nested-call":
        # CALL changes cmd.exe's batch return behavior. Keep this control separate
        # from direct process invocation, which previously swallowed failures.
        (tmp_path / "caller.bat").write_text(
            "@echo off\ncall scripts\\test.bat\nexit /b %ERRORLEVEL%\n", encoding="utf-8"
        )
        script = "caller.bat"

    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "cmd /d /c exit " + str(initial_exit_code) + " & " + script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    expected_summary = {0: "1 passed", 1: "1 failed", 5: "no tests ran"}[pytest_exit_code]
    assert expected_summary in result.stdout, result.stdout + result.stderr
    assert result.returncode == pytest_exit_code, result.stdout + result.stderr
