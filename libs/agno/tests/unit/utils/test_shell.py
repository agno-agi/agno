"""Tests for the command output helpers in agno.utils.shell."""

import locale
import sys

import pytest

from agno.utils.shell import decode_command_output, run_and_decode


def test_decode_command_output_reads_utf8(cp1252_subprocess_encoding):
    """UTF-8 output is read as UTF-8, whatever the machine's default encoding is."""
    assert decode_command_output("He said \u201chi\u201d".encode("utf-8")) == "He said \u201chi\u201d"


def test_decode_command_output_falls_back_to_the_default_encoding(cp1252_subprocess_encoding):
    """Output that is not valid UTF-8 is read with the machine's default encoding."""
    # E9 is e-acute in cp1252 and is not valid UTF-8 on its own.
    assert decode_command_output(b"caf" + bytes([0xE9])) == "caf\u00e9"


def test_decode_command_output_replaces_bytes_it_cannot_decode(monkeypatch):
    """Bytes that neither encoding can decode become the replacement character."""
    monkeypatch.setattr(locale, "getpreferredencoding", lambda do_setlocale=True: "utf-8")
    assert decode_command_output(b"caf" + bytes([0xE9])) == "caf\ufffd"


def test_decode_command_output_normalizes_line_endings():
    assert decode_command_output(b"one\r\ntwo\rthree\n") == "one\ntwo\nthree\n"


@pytest.mark.parametrize("data", [None, b""])
def test_decode_command_output_of_no_output_is_empty(data):
    assert decode_command_output(data) == ""


def test_run_and_decode_returns_the_exit_code_and_decoded_output():
    script = "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"
    result = run_and_decode([sys.executable, "-c", script])
    assert (result.returncode, result.stdout, result.stderr) == (3, "out\n", "err\n")
