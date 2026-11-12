import locale
from typing import List

from agno.utils.log import log_debug, log_info, log_warning


def decode_subprocess_output(data: bytes) -> str:
    """Decode subprocess output to text without ever raising.

    Tries UTF-8 first (what most tools print), then the locale encoding
    (e.g. cp1252 on Windows, where a child may emit locale-encoded bytes),
    and finally UTF-8 with replacement characters, so undecodable bytes
    degrade to U+FFFD instead of failing the tool call.

    :param data: Raw bytes captured from a subprocess stream.
    :return: Decoded text.
    """
    if not data:
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return data.decode(locale.getpreferredencoding(False))
    except (UnicodeDecodeError, LookupError):
        return data.decode("utf-8", errors="replace")


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
