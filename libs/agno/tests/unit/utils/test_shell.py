"""Tests for agno.utils.shell helpers."""

import locale
import sys

from agno.utils.shell import decode_subprocess_output, run_shell_command


def test_decode_subprocess_output_utf8():
    assert decode_subprocess_output("He said \u201chi\u201d".encode("utf-8")) == "He said \u201chi\u201d"


def test_decode_subprocess_output_empty():
    assert decode_subprocess_output(b"") == ""


def test_decode_subprocess_output_invalid_bytes_use_replacement():
    # A lone 0xe9 byte is not valid UTF-8 and not decodable as ASCII
    # (the POSIX locale encoding), so it degrades to U+FFFD.
    assert decode_subprocess_output(b"caf" + bytes([0xE9])) == "caf\ufffd"


def test_decode_subprocess_output_falls_back_to_locale_encoding(monkeypatch):
    # A cp1252 locale reads the same byte as e-acute instead of replacing it.
    monkeypatch.setattr(locale, "getpreferredencoding", lambda do_setlocale=False: "cp1252")
    assert decode_subprocess_output(b"caf" + bytes([0xE9])) == "caf\u00e9"


def test_run_shell_command_non_utf8_bytes_do_not_error():
    """Undecodable stdout must not fail the call (#11580)."""
    out = run_shell_command([sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'caf' + bytes([0xE9]))"])
    assert out == "caf\ufffd"
    assert not out.startswith("Error")
