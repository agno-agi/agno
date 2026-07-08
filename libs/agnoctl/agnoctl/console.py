"""Console output helpers.

Two output modes exist for every command: human (rich, colored, informative) and machine
(--json: a single JSON document on stdout, nothing else). Commands build a payload dict as
they work; in JSON mode only emit_json touches stdout, so output stays parseable.
"""

import json
from typing import Any, Dict

from rich.console import Console

console = Console()
err_console = Console(stderr=True)


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
