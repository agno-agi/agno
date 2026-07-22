"""Console output helpers.

Two output modes exist for every command: human (rich, colored, informative) and machine
(--json: a single JSON document on stdout, nothing else). Commands build a payload dict as
they work; in JSON mode only emit_json touches stdout, so output stays parseable.
"""

import json
from pathlib import Path
from typing import Any, Dict

from rich.console import Console

console = Console()
err_console = Console(stderr=True)


def shorten_home(text: str) -> str:
    """Display-only: the home-directory prefix reads better as ~. Never used in JSON."""
    home = str(Path.home())
    if home and home != "/" and home in text:
        return text.replace(home, "~")
    return text


def print_heading(msg: str) -> None:
    console.print(msg, style="green bold")


def print_info(msg: str) -> None:
    console.print(msg)


def print_success(msg: str) -> None:
    console.print(msg, style="chartreuse3")


def print_warning(msg: str) -> None:
    err_console.print(msg, style="magenta")


def print_error(msg: str) -> None:
    err_console.print(msg, style="red")


def emit_json(payload: Dict[str, Any]) -> None:
    """Print the machine-readable result document. The only stdout writer in --json mode."""
    print(json.dumps(payload, indent=2, sort_keys=False, default=str))
