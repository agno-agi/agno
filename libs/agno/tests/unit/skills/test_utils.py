"""Tests for agno.skills.utils."""

from agno.skills.utils import run_script


def test_run_script_non_utf8_bytes_do_not_error(tmp_path):
    """A script printing undecodable bytes must not fail the call (#11580)."""
    script = tmp_path / "print_bytes.py"
    script.write_text("#!/usr/bin/env python3\nimport sys\nsys.stdout.buffer.write(b'caf' + bytes([0xE9]))\n")
    script.chmod(0o755)

    result = run_script(script)

    assert result.returncode == 0
    assert result.stdout == "caf\ufffd"
    assert result.stderr == ""


def test_run_script_returns_decoded_stdout(tmp_path):
    """Plain UTF-8 script output is decoded as before."""
    script = tmp_path / "hello.py"
    script.write_text("#!/usr/bin/env python3\nprint('hello')\n")
    script.chmod(0o755)

    result = run_script(script)

    assert result.returncode == 0
    assert result.stdout == "hello\n"
