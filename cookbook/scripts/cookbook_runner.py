"""Run cookbook scripts and report what passed.

Cookbooks make real model calls, so a full folder is slow and expensive. This
runner exists to make that survivable: it CAPTURES each script's output so a
failure can be triaged from the report instead of by scrolling the terminal,
shows live progress, and can run several scripts at once.

    python cookbook/scripts/cookbook_runner.py cookbook/environments/_00_quickstart
    python cookbook/scripts/cookbook_runner.py cookbook/environments -r --concurrency 4
    python cookbook/scripts/cookbook_runner.py cookbook/environments -r --pattern basic.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

SKIP_FILE_NAMES = {"__init__.py"}
# `data` holds fixtures and generated exports, never runnable examples.
SKIP_DIR_NAMES = {"__pycache__", "data"}
# Enough tail to hold a traceback and the failing assertion, without pasting a
# whole rollout transcript into the report.
FAILURE_TAIL_LINES = 40

console = Console()
app = typer.Typer(add_completion=False, help=__doc__)


@dataclass
class Result:
    script: str
    status: str  # PASS | FAIL | TIMEOUT
    returncode: int
    duration_seconds: float
    attempts: int = 1
    error: Optional[str] = None
    output_tail: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "PASS"


def resolve_python(python_bin: Optional[str]) -> str:
    """Prefer the demo venv: cookbooks need model SDKs the dev venv may lack."""
    if python_bin:
        return python_bin
    demo = Path(".venvs/demo/bin/python")
    return demo.as_posix() if demo.exists() else sys.executable


def discover(directory: Path, recursive: bool, pattern: Optional[str]) -> List[Path]:
    walker = directory.rglob("*.py") if recursive else directory.glob("*.py")
    found = [
        path
        for path in walker
        if path.name not in SKIP_FILE_NAMES
        and not any(part in SKIP_DIR_NAMES for part in path.parts)
        and (pattern is None or fnmatch(path.name, pattern))
    ]
    return sorted(found)


def _as_text(value: object) -> str:
    """TimeoutExpired carries RAW BYTES even under text=True -- decoding only
    happens on the normal return path -- and stderr may be None. Both must be
    normalised before they are joined."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _first_exception_line(output: str) -> Optional[str]:
    """The exception line is what belongs in a summary row; the full tail stays
    in the report."""
    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if stripped and (("Error" in stripped and ":" in stripped) or stripped.startswith("assert")):
            return stripped[:200]
    return None


def run_once(script: Path, python_bin: str, timeout: int) -> Result:
    """One attempt. Output is captured rather than streamed: under concurrency
    interleaved streams are unreadable, and the tail is what makes a failure
    diagnosable from the report alone."""
    start = time.perf_counter()
    try:
        completed = subprocess.run(
            # -u keeps the child's stdout unbuffered: without it a timed-out
            # script's partial output dies with the kill, and a timeout is
            # exactly when you want to see how far it got.
            [python_bin, "-u", script.as_posix()],
            capture_output=True,
            text=True,
            timeout=timeout if timeout > 0 else None,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        partial = _as_text(exc.stdout) + _as_text(exc.stderr)
        return Result(
            script=script.as_posix(),
            status="TIMEOUT",
            returncode=124,
            duration_seconds=round(time.perf_counter() - start, 2),
            error=f"exceeded {timeout}s",
            output_tail=partial.splitlines()[-FAILURE_TAIL_LINES:],
        )
    except OSError as exc:
        return Result(
            script=script.as_posix(),
            status="FAIL",
            returncode=1,
            duration_seconds=round(time.perf_counter() - start, 2),
            error=str(exc),
        )

    duration = round(time.perf_counter() - start, 2)
    combined = _as_text(completed.stdout) + _as_text(completed.stderr)
    if completed.returncode == 0:
        return Result(script.as_posix(), "PASS", 0, duration)
    return Result(
        script=script.as_posix(),
        status="FAIL",
        returncode=completed.returncode,
        duration_seconds=duration,
        error=_first_exception_line(combined),
        output_tail=combined.splitlines()[-FAILURE_TAIL_LINES:],
    )


def run_with_retries(script: Path, python_bin: str, timeout: int, retries: int) -> Result:
    result = run_once(script, python_bin, timeout)
    attempt = 1
    while not result.ok and attempt <= retries:
        attempt += 1
        result = run_once(script, python_bin, timeout)
    result.attempts = attempt
    return result


def render_summary(results: List[Result], root: Path) -> None:
    table = Table(title="Cookbook run", header_style="bold")
    table.add_column("Script", overflow="fold")
    table.add_column("Status", justify="center")
    table.add_column("Time", justify="right")
    table.add_column("Why it failed", overflow="fold")

    for result in results:
        style = {"PASS": "green", "FAIL": "red", "TIMEOUT": "yellow"}[result.status]
        try:
            name = Path(result.script).relative_to(root).as_posix()
        except ValueError:
            name = result.script
        retry_note = "" if result.attempts == 1 else f" (x{result.attempts})"
        table.add_row(
            name,
            f"[{style}]{result.status}[/{style}]{retry_note}",
            f"{result.duration_seconds}s",
            result.error or "",
        )
    console.print(table)

    failed = [r for r in results if not r.ok]
    passed = len(results) - len(failed)
    total_time = round(sum(r.duration_seconds for r in results), 1)
    console.print(
        f"\n[bold]{passed}/{len(results)} passed[/bold] in {total_time}s"
        + (f"  [red]{len(failed)} failed[/red]" if failed else "")
    )
    # The tail is the point: a failure should be diagnosable without re-running.
    for result in failed:
        console.print(f"\n[red]{'-' * 70}[/red]\n[red]{result.script}[/red]")
        for line in result.output_tail:
            console.print(f"  {line}", highlight=False)


@app.command()
def main(
    directory: Path = typer.Argument(..., exists=True, file_okay=False, help="Folder of cookbooks to run."),
    recursive: bool = typer.Option(False, "--recursive", "-r", help="Include subfolders."),
    pattern: Optional[str] = typer.Option(None, "--pattern", help="Only run files matching a glob, e.g. basic.py"),
    concurrency: int = typer.Option(1, "--concurrency", "-c", min=1, help="Scripts to run at once."),
    timeout_seconds: int = typer.Option(1800, "--timeout-seconds", help="Per-script timeout. 0 disables."),
    retries: int = typer.Option(0, "--retries", min=0, help="Retries for a failing script."),
    python_bin: Optional[str] = typer.Option(None, "--python-bin", help="Defaults to .venvs/demo/bin/python."),
    json_report: Optional[Path] = typer.Option(None, "--json-report", help="Write machine-readable results."),
    list_only: bool = typer.Option(False, "--list", help="List what would run, then exit."),
) -> None:
    scripts = discover(directory, recursive, pattern)
    if not scripts:
        console.print(f"[yellow]No scripts found under {directory}[/yellow]")
        raise typer.Exit(1)

    if list_only:
        for script in scripts:
            console.print(script.as_posix())
        raise typer.Exit(0)

    interpreter = resolve_python(python_bin)
    console.print(
        f"[bold]{len(scripts)}[/bold] script(s) - {interpreter} - "
        f"timeout {timeout_seconds or 'off'}s - concurrency {concurrency}\n"
    )

    results: List[Result] = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("running", total=len(scripts))
        if concurrency == 1:
            for script in scripts:
                progress.update(task, description=script.name)
                results.append(run_with_retries(script, interpreter, timeout_seconds, retries))
                progress.advance(task)
        else:
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = {
                    pool.submit(run_with_retries, script, interpreter, timeout_seconds, retries): script
                    for script in scripts
                }
                for future in as_completed(futures):
                    results.append(future.result())
                    progress.update(task, description=futures[future].name)
                    progress.advance(task)
            results.sort(key=lambda item: item.script)

    render_summary(results, directory)

    if json_report:
        json_report.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "directory": directory.resolve().as_posix(),
            "python_bin": interpreter,
            "timeout_seconds": timeout_seconds,
            "concurrency": concurrency,
            "summary": {
                "total": len(results),
                "passed": sum(1 for item in results if item.ok),
                "failed": sum(1 for item in results if item.status == "FAIL"),
                "timed_out": sum(1 for item in results if item.status == "TIMEOUT"),
            },
            "results": [asdict(item) for item in results],
        }
        json_report.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        console.print(f"\nReport: {json_report}")

    raise typer.Exit(0 if all(item.ok for item in results) else 1)


if __name__ == "__main__":
    app()
