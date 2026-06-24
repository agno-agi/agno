from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import click

try:
    import inquirer
except ImportError:  # pragma: no cover - optional dependency for interactive mode
    inquirer = None


SKIP_FILE_NAMES = {"__init__.py"}
SKIP_DIR_NAMES = {"__pycache__"}


def resolve_python_bin(python_bin: str | None) -> str:
    if python_bin:
        return python_bin
    demo_python = Path(".venvs/demo/bin/python")
    if demo_python.exists():
        return demo_python.as_posix()
    return sys.executable


def select_directory(base_directory: Path) -> Path | None:
    if inquirer is None:
        raise click.ClickException(
            "Interactive mode requires `inquirer`. Install it or use `--batch`."
        )

    current_dir = base_directory
    while True:
        items = [
            item.name
            for item in current_dir.iterdir()
            if item.is_dir() and item.name not in SKIP_DIR_NAMES
        ]
        items.sort()
        items.insert(0, "[Select this directory]")
        if current_dir != current_dir.parent:
            items.insert(1, "[Go back]")

        questions = [
            inquirer.List(
                "selected_item",
                message=f"Current directory: {current_dir.as_posix()}",
                choices=items,
            )
        ]
        answers = inquirer.prompt(questions)
        if not answers or "selected_item" not in answers:
            click.echo("No selection made. Exiting.")
            return None

        selected_item = answers["selected_item"]
        if selected_item == "[Select this directory]":
            return current_dir
        if selected_item == "[Go back]":
            current_dir = current_dir.parent
            continue
        current_dir = current_dir / selected_item


def list_python_files(base_directory: Path, recursive: bool) -> list[Path]:
    pattern = "**/*.py" if recursive else "*.py"
    files = []
    for path in sorted(base_directory.glob(pattern)):
        if not path.is_file():
            continue
        if path.name in SKIP_FILE_NAMES:
            continue
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        files.append(path)
    return files


def run_python_script(
    script_path: Path, python_bin: str, timeout_seconds: int
) -> dict[str, object]:
    click.echo(f"Running {script_path.as_posix()} with {python_bin}")
    start = time.perf_counter()
    timed_out = False
    return_code = 1
    error_message = None
    try:
        completed = subprocess.run(
            [python_bin, script_path.as_posix()],
            check=False,
            timeout=timeout_seconds if timeout_seconds > 0 else None,
            text=True,
        )
        return_code = completed.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        error_message = f"Timed out after {timeout_seconds}s"
        return_code = 124
        click.echo(f"Timeout: {script_path.as_posix()} exceeded {timeout_seconds}s")
    except OSError as exc:
        error_message = str(exc)
        click.echo(f"Error running {script_path.as_posix()}: {exc}")

    duration = time.perf_counter() - start
    passed = return_code == 0 and not timed_out
    return {
        "script": script_path.as_posix(),
        "status": "PASS" if passed else "FAIL",
        "return_code": return_code,
        "timed_out": timed_out,
        "duration_seconds": round(duration, 3),
        "error": error_message,
    }


def run_with_retries(
    script_path: Path, python_bin: str, timeout_seconds: int, retries: int
) -> dict[str, object]:
    attempts = 0
    result: dict[str, object] | None = None
    while attempts <= retries:
        attempts += 1
        result = run_python_script(
            script_path=script_path,
            python_bin=python_bin,
            timeout_seconds=timeout_seconds,
        )
        if result["status"] == "PASS":
            break
        if attempts <= retries:
            click.echo(
                f"Retry {attempts}/{retries} for {script_path.as_posix()} after failure"
            )
    if result is None:
        raise RuntimeError(f"No execution result for {script_path.as_posix()}")
    result["attempts"] = attempts
    return result


def summarize_results(results: list[dict[str, object]]) -> dict[str, int]:
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = len(results) - passed
    timed_out = sum(1 for r in results if r["timed_out"])
    return {
        "total_scripts": len(results),
        "passed": passed,
        "failed": failed,
        "timed_out": timed_out,
    }


def write_json_report(
    output_path: str,
    base_directory: Path,
    selected_directory: Path,
    mode: str,
    recursive: bool,
    python_bin: str,
    timeout_seconds: int,
    retries: int,
    results: list[dict[str, object]],
) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_directory": base_directory.resolve().as_posix(),
        "selected_directory": selected_directory.resolve().as_posix(),
        "mode": mode,
        "recursive": recursive,
        "python_bin": python_bin,
        "timeout_seconds": timeout_seconds,
        "retries": retries,
        "summary": summarize_results(results),
        "results": results,
    }
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    click.echo(f"Wrote JSON report to {path.as_posix()}")


def select_interactive_action() -> str | None:
    if inquirer is None:
        return None
    questions = [
        inquirer.List(
            "action",
            message="Some cookbooks failed. What would you like to do?",
            choices=["Retry failed scripts", "Exit with error log"],
        )
    ]
    answers = inquirer.prompt(questions)
    return answers.get("action") if answers else None


@click.command()
@click.argument(
    "base_directory",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    default="cookbook",
)
@click.option(
    "--batch",
    is_flag=True,
    default=False,
    help="Non-interactive mode: run all scripts in the selected directory.",
)
@click.option(
    "--recursive/--no-recursive",
    default=False,
    help="Include Python scripts recursively under selected directory.",
)
@click.option(
    "--python-bin",
    default=None,
    help="Python executable to use. Defaults to .venvs/demo/bin/python if available.",
)
@click.option(
    "--timeout-seconds",
    default=0,
    show_default=True,
    type=int,
    help="Per-script timeout. Set 0 to disable timeouts.",
)
@click.option(
    "--retries",
    default=0,
    show_default=True,
    type=int,
    help="Number of retry attempts for failed scripts.",
)
@click.option(
    "--fail-fast",
    is_flag=True,
    default=False,
    help="Stop after the first failure.",
)
@click.option(
    "--json-report",
    default=None,
    help="Optional path to write machine-readable JSON results.",
)
def drill_and_run_scripts(
    base_directory: str,
    batch: bool,
    recursive: bool,
    python_bin: str | None,
    timeout_seconds: int,
    retries: int,
    fail_fast: bool,
    json_report: str | None,
) -> None:
    """Run cookbook scripts in interactive or batch mode."""
    if timeout_seconds < 0:
        raise click.ClickException("--timeout-seconds must be >= 0")
    if retries < 0:
        raise click.ClickException("--retries must be >= 0")

    base_dir_path = Path(base_directory)
    selected_directory = (
        base_dir_path if batch else select_directory(base_directory=base_dir_path)
    )
    if selected_directory is None:
        raise SystemExit(1)

    resolved_python_bin = resolve_python_bin(python_bin=python_bin)
    click.echo(f"Selected directory: {selected_directory.as_posix()}")
    click.echo(f"Python executable: {resolved_python_bin}")
    click.echo(f"Recursive: {recursive}")
    click.echo(f"Timeout (seconds): {timeout_seconds}")
    click.echo(f"Retries: {retries}")

    python_files = list_python_files(
        base_directory=selected_directory, recursive=recursive
    )
    if not python_files:
        click.echo("No runnable .py files found.")
        raise SystemExit(0)

    click.echo(f"Discovered {len(python_files)} script(s).")
    results: list[dict[str, object]] = []

    pending = python_files
    while pending:
        failures: list[Path] = []
        for script_path in pending:
            result = run_with_retries(
                script_path=script_path,
                python_bin=resolved_python_bin,
                timeout_seconds=timeout_seconds,
                retries=retries,
            )
            results.append(result)
            if result["status"] == "FAIL":
                failures.append(script_path)
                if fail_fast:
                    pending = []
                    break

        if not failures:
            break
        if batch:
            break

        click.echo("\n--- Error Log ---")
        for failure in failures:
            click.echo(f"- {failure.as_posix()}")

        action = select_interactive_action()
        if action == "Retry failed scripts":
            click.echo("Re-running failed scripts.")
            pending = failures
            continue
        break

    summary = summarize_results(results)
    click.echo(
        "Summary: "
        f"total={summary['total_scripts']} "
        f"passed={summary['passed']} "
        f"failed={summary['failed']} "
        f"timed_out={summary['timed_out']}"
    )

    if json_report:
        write_json_report(
            output_path=json_report,
            base_directory=base_dir_path,
            selected_directory=selected_directory,
            mode="batch" if batch else "interactive",
            recursive=recursive,
            python_bin=resolved_python_bin,
            timeout_seconds=timeout_seconds,
            retries=retries,
            results=results,
        )

    if summary["failed"] > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    drill_and_run_scripts()
