import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Requires the Windows command processor")


@pytest.mark.parametrize(
    ("agno_exit", "infra_exit", "expected_exit", "expected_children"),
    [
        (0, 0, 0, ["agno", "agno_infra"]),
        (7, 0, 7, ["agno"]),
        (0, 9, 9, ["agno", "agno_infra"]),
        (7, 9, 7, ["agno"]),
        (None, 9, 9, ["agno_infra"]),
        (0, None, 0, ["agno"]),
    ],
)
def test_windows_validation_reports_child_result(tmp_path, agno_exit, infra_exit, expected_exit, expected_children):
    # Include spaces to exercise the wrapper's quoting as well as its exit handling.
    repo = tmp_path / "repo with spaces"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    source = Path(__file__).resolve().parents[4] / "scripts" / "validate.bat"
    wrapper = scripts / "validate.bat"
    shutil.copyfile(source, wrapper)

    for library, exit_code in [("agno", agno_exit), ("agno_infra", infra_exit)]:
        child_dir = repo / "libs" / library / "scripts"
        child_dir.mkdir(parents=True)
        if exit_code is not None:
            (child_dir / "validate.bat").write_text(
                f"@echo off\necho RAN-{library}\nexit /b {exit_code}\n", encoding="utf-8"
            )

    result = subprocess.run(
        [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(wrapper)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == expected_exit, result.stdout + result.stderr
    assert [
        line.removeprefix("RAN-") for line in result.stdout.splitlines() if line.startswith("RAN-")
    ] == expected_children
    assert ("All validations complete." in result.stdout) == (expected_exit == 0)
    if expected_exit:
        assert f"failed with exit code {expected_exit}" in result.stdout
