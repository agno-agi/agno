"""Tests for agno.utils.shell helpers."""

import locale
import sys

from agno.utils.shell import decode_subprocess_output, run_shell_command


def test_decode_subprocess_output_utf8():
    assert decode_subprocess_output("He said \u201chi\u201d".encode("utf-8")) == "He said \u201chi\u201d"


def test_decode_subprocess_output_empty():
    assert decode_subprocess_output(b"") == ""


def test_decode_subprocess_output_invalid_bytes_use_replacement(monkeypatch):
    # A lone 0xe9 byte is not valid UTF-8 and not decodable as ASCII
    # (the POSIX locale encoding), so it degrades to U+FFFD.
    # Pin the locale: on a cp1252 machine (e.g. Windows CI) the same byte
    # would otherwise decode as e-acute and this assertion would fail.
    monkeypatch.setattr(locale, "getpreferredencoding", lambda do_setlocale=False: "ascii")
    assert decode_subprocess_output(b"caf" + bytes([0xE9])) == "caf\ufffd"


def test_decode_subprocess_output_falls_back_to_locale_encoding(monkeypatch):
    # A cp1252 locale reads the same byte as e-acute instead of replacing it.
    monkeypatch.setattr(locale, "getpreferredencoding", lambda do_setlocale=False: "cp1252")
    assert decode_subprocess_output(b"caf" + bytes([0xE9])) == "caf\u00e9"


def test_decode_subprocess_output_skips_never_fail_locale_encoding(monkeypatch):
    # latin-1 decodes every byte, so falling back to it would silently turn
    # a stray byte into a latin-1 character instead of keeping U+FFFD.
    monkeypatch.setattr(locale, "getpreferredencoding", lambda do_setlocale=False: "latin-1")
    assert decode_subprocess_output(b"caf" + bytes([0xE9])) == "caf\ufffd"


def test_decode_subprocess_output_keeps_utf8_text_with_one_bad_byte(monkeypatch):
    # Valid UTF-8 around a single stray byte must not be reread as cp1252 mojibake.
    monkeypatch.setattr(locale, "getpreferredencoding", lambda do_setlocale=False: "cp1252")
    assert decode_subprocess_output("café ".encode("utf-8") + bytes([0xE9])) == "café \ufffd"


def test_decode_subprocess_output_normalizes_line_endings():
    # Restores the universal-newline conversion of the old text=True calls.
    assert decode_subprocess_output(b"one\r\ntwo\rthree\n") == "one\ntwo\nthree\n"


def test_run_shell_command_normalizes_crlf_output():
    """CRLF output from a child must come back with plain newlines (#11590)."""
    out = run_shell_command([sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'one\\r\\ntwo\\r\\n')"])
    assert out == "one\ntwo\n"


def test_run_shell_command_non_utf8_bytes_do_not_error(monkeypatch):
    """Undecodable stdout must not fail the call (#11580)."""
    # Pin the locale: on a cp1252 machine (e.g. Windows CI) the byte would
    # otherwise decode as e-acute and this assertion would fail.
    monkeypatch.setattr(locale, "getpreferredencoding", lambda do_setlocale=False: "ascii")
    out = run_shell_command([sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'caf' + bytes([0xE9]))"])
    assert out == "caf\ufffd"
    assert not out.startswith("Error")
