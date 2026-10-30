"""Unit tests for skill executors."""

from pathlib import Path

import pytest

from agno.skills.executor import LocalSkillExecutor, SkillExecutor
from agno.skills.utils import ScriptResult, run_script


@pytest.fixture
def echo_script(tmp_path: Path) -> Path:
    """Create an executable script that prints its arguments and its working directory."""
    script = tmp_path / "echo.py"
    script.write_text(
        "#!/usr/bin/env python3\nimport os, sys\nprint(os.getcwd(), *sys.argv[1:])\n",
        encoding="utf-8",
    )
    return script


# --- Contract Tests ---


def test_skill_executor_is_abstract() -> None:
    """Test that SkillExecutor cannot be instantiated without a run implementation."""
    with pytest.raises(TypeError):
        SkillExecutor()  # type: ignore[abstract]


def test_local_executor_is_a_skill_executor() -> None:
    """Test that the shipped executor satisfies the SkillExecutor contract."""
    assert isinstance(LocalSkillExecutor(), SkillExecutor)


# --- LocalSkillExecutor Tests ---


def test_local_executor_matches_run_script(echo_script: Path, tmp_path: Path) -> None:
    """Test that the default executor produces exactly what calling run_script produces."""
    via_executor = LocalSkillExecutor().run(echo_script, args=["one", "two"], timeout=10, cwd=tmp_path)
    via_run_script = run_script(script_path=echo_script, args=["one", "two"], timeout=10, cwd=tmp_path)

    assert isinstance(via_executor, ScriptResult)
    assert via_executor == via_run_script


def test_local_executor_passes_cwd(echo_script: Path, tmp_path: Path) -> None:
    """Test that the executor runs the script in the working directory it was given."""
    other_dir = tmp_path / "elsewhere"
    other_dir.mkdir()

    result = LocalSkillExecutor().run(echo_script, cwd=other_dir)

    assert result.returncode == 0
    assert str(other_dir.resolve()) in result.stdout


def test_local_executor_propagates_timeout(tmp_path: Path) -> None:
    """Test that the executor lets a timeout propagate rather than swallowing it."""
    import subprocess

    script = tmp_path / "sleep.py"
    script.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(30)\n", encoding="utf-8")

    with pytest.raises(subprocess.TimeoutExpired):
        LocalSkillExecutor().run(script, timeout=1)
