import locale
import subprocess
from typing import Any, List, Optional, Sequence, Union

from agno.utils.log import log_debug, log_info, log_warning


def decode_command_output(data: Optional[bytes]) -> str:
    """Decode the output captured from a command.

    Most tools print UTF-8, so that is tried first. Output that is not valid UTF-8 is read with
    the machine's default encoding instead, which is what many Windows programs print in. Bytes
    that encoding cannot decode become the replacement character, so decoding never fails.
    Line endings are normalized to a newline, as subprocess does when it decodes the output.
    """
    if not data:
        return ""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode(locale.getpreferredencoding(False), errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def run_and_decode(args: Union[str, Sequence[str]], **kwargs: Any) -> "subprocess.CompletedProcess[str]":
    """Run a command with subprocess.run and decode what it prints with decode_command_output.

    Takes the keyword arguments of subprocess.run, other than the ones that choose how the
    output is captured or decoded.
    """
    result = subprocess.run(args, capture_output=True, **kwargs)
    return subprocess.CompletedProcess(
        result.args,
        result.returncode,
        decode_command_output(result.stdout),
        decode_command_output(result.stderr),
    )


def run_shell_command(args: List[str], tail: int = 100) -> str:
    log_info(f"Running shell command: {args}")

    try:
        result = run_and_decode(args)
        log_debug(f"Result: {result}")
        log_debug(f"Return code: {result.returncode}")
        if result.returncode != 0:
            return f"Error: {result.stderr}"

        # return only the last n lines of the output; tail=0 returns nothing
        # ([-0:] would return the whole output).
        return "\n".join(result.stdout.split("\n")[-tail:]) if tail > 0 else ""
    except Exception as e:
        log_warning(f"Failed to run shell command: {str(e)}")
        return f"Error: {e}"
