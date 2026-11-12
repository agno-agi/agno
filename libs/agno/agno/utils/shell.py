import locale
from typing import List

from agno.utils.log import log_debug, log_info, log_warning


def decode_subprocess_output(data: bytes) -> str:
    """Decode subprocess output to text without ever raising.

    Tries UTF-8 first (what most tools print). If that fails, decodes as
    UTF-8 with replacement characters: when the result still contains valid
    non-ASCII characters, the output is mostly UTF-8 with a few bad bytes,
    so those characters are kept instead of rereading the whole stream as
    the locale encoding (which would mangle them). Only when nothing
    decoded cleanly as UTF-8 does it fall back to the locale encoding
    (e.g. cp1252 on Windows, where a child may emit locale-encoded bytes).

    Line endings are normalized to "\\n" (universal-newline conversion),
    matching the previous `text=True` behaviour of the replaced
    `subprocess.run` calls.

    :param data: Raw bytes captured from a subprocess stream.
    :return: Decoded text.
    """
    if not data:
        return ""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")
        if not any(ord(ch) > 127 and ch != "\ufffd" for ch in text):
            try:
                text = data.decode(locale.getpreferredencoding(False))
            except (UnicodeDecodeError, LookupError):
                pass
    return text.replace("\r\n", "\n").replace("\r", "\n")


def run_shell_command(args: List[str], tail: int = 100) -> str:
    log_info(f"Running shell command: {args}")

    import subprocess

    try:
        result = subprocess.run(args, capture_output=True)
        log_debug(f"Result: {result}")
        log_debug(f"Return code: {result.returncode}")
        if result.returncode != 0:
            return f"Error: {decode_subprocess_output(result.stderr)}"

        # return only the last n lines of the output
        stdout = decode_subprocess_output(result.stdout)
        return "\n".join(stdout.split("\n")[-tail:])
    except Exception as e:
        log_warning(f"Failed to run shell command: {str(e)}")
        return f"Error: {e}"
