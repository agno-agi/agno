"""
Run evaluations against demo agents, teams, and workflows.

Usage:
    python -m evals.run_evals
    python -m evals.run_evals --agent dash
    python -m evals.run_evals --agent seek --verbose
    python -m evals.run_evals --category dash_basic
"""

import argparse
import time
from typing import TypedDict

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)
from rich.table import Table
from rich.text import Text

from evals.test_cases import AGENT_TESTS, ALL_TEST_CASES, CATEGORIES


class EvalResult(TypedDict, total=False):
    status: str
    agent: str
    question: str
    category: str
    missing: list[str] | None
    duration: float
    response: str | None
    error: str


console = Console()


def get_component(agent_id: str):
    """Get the agent, team, or workflow instance by ID."""
    if agent_id == "gcode":
        from agents.gcode import gcode

        return gcode
    elif agent_id == "dash":
        from agents.dash import dash

        return dash
    elif agent_id == "pal":
        from agents.pal import pal

        return pal
    elif agent_id == "scout":
        from agents.scout import scout

        return scout
    elif agent_id == "seek":
        from agents.seek import seek

        return seek
    elif agent_id == "research-team":
        from teams.research import research_team

        return research_team
    elif agent_id == "daily-brief":
        from workflows.daily_brief import daily_brief_workflow

        return daily_brief_workflow
    else:
        raise ValueError(f"Unknown component: {agent_id}")


def check_strings(response: str, expected: list[str], mode: str = "all") -> list[str]:
    """Check which expected strings are missing from the response."""
    response_lower = response.lower()
    missing = [v for v in expected if v.lower() not in response_lower]
    if mode == "any":
        # For "any" mode, all are "missing" only if none matched
        if len(missing) < len(expected):
            return []  # At least one matched
    return missing


def run_evals(
    agent: str | None = None,
    category: str | None = None,
    verbose: bool = False,
) -> tuple[int, int, int]:
    """Run evaluation suite."""
    # Select tests
    if agent:
        tests = AGENT_TESTS.get(agent, [])
        if not tests:
            console.print(f"[red]No tests found for agent: {agent}[/red]")
            console.print(f"[dim]Available: {', '.join(AGENT_TESTS.keys())}[/dim]")
            return 0, 0, 1
    else:
        tests = ALL_TEST_CASES

    if category:
        tests = [tc for tc in tests if tc.category == category]
        if not tests:
            console.print(f"[red]No tests found for category: {category}[/red]")
            return 0, 0, 1

    console.print(
        Panel(
            f"[bold]Running {len(tests)} tests[/bold]\nMode: String matching",
            style="blue",
        )
    )

    results: list[EvalResult] = []
    start = time.time()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Evaluating...", total=len(tests))

        for test_case in tests:
            progress.update(
                task,
                description=f"[cyan]{test_case.agent}: {test_case.question[:35]}...[/cyan]",
            )
            test_start = time.time()

            try:
                component = get_component(test_case.agent)
                result = component.run(test_case.question)
                response = result.content or ""
                duration = time.time() - test_start

                missing = check_strings(
                    response, test_case.expected_strings, test_case.match_mode
                )
                status = "PASS" if not missing else "FAIL"

                results.append(
                    {
                        "status": status,
                        "agent": test_case.agent,
                        "question": test_case.question,
                        "category": test_case.category,
                        "missing": missing if missing else None,
                        "duration": duration,
                        "response": response if verbose else None,
                    }
                )

            except Exception as e:
                duration = time.time() - test_start
                results.append(
                    {
                        "status": "ERROR",
                        "agent": test_case.agent,
                        "question": test_case.question,
                        "category": test_case.category,
                        "missing": None,
                        "duration": duration,
                        "error": str(e),
                        "response": None,
                    }
                )

            progress.advance(task)

    total_duration = time.time() - start
    display_results(results, verbose)
    display_summary(results, total_duration)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    errors = sum(1 for r in results if r["status"] == "ERROR")
    return passed, failed, errors


def display_results(results: list[EvalResult], verbose: bool):
    """Display results table."""
    table = Table(title="Results", show_lines=True)
    table.add_column("Status", style="bold", width=6)
    table.add_column("Agent", style="dim", width=14)
    table.add_column("Question", width=40)
    table.add_column("Time", justify="right", width=6)
    table.add_column("Notes", width=30)

    for r in results:
        if r["status"] == "PASS":
            status = Text("PASS", style="green")
            notes = ""
        elif r["status"] == "FAIL":
            status = Text("FAIL", style="red")
            missing = r.get("missing")
            notes = f"Missing: {', '.join(missing[:2])}" if missing else ""
        else:
            status = Text("ERR", style="yellow")
            notes = (r.get("error") or "")[:30]

        table.add_row(
            status,
            r["agent"],
            r["question"][:38] + "..." if len(r["question"]) > 38 else r["question"],
            f"{r['duration']:.1f}s",
            notes,
        )

    console.print(table)

    if verbose:
        failures = [r for r in results if r["status"] == "FAIL" and r.get("response")]
        if failures:
            console.print("\n[bold red]Failed Responses:[/bold red]")
            for r in failures:
                resp = r["response"] or ""
                panel_content = resp[:500] + "..." if len(resp) > 500 else resp
                console.print(
                    Panel(
                        panel_content,
                        title=f"[red]{r['agent']}: {r['question'][:50]}[/red]",
                        border_style="red",
                    )
                )


def display_summary(results: list[EvalResult], total_duration: float):
    """Display summary statistics."""
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    errors = sum(1 for r in results if r["status"] == "ERROR")
    total = len(results)
    rate = (passed / total * 100) if total else 0

    summary = Table.grid(padding=(0, 2))
    summary.add_column(style="bold")
    summary.add_column()

    summary.add_row("Total:", f"{total} tests in {total_duration:.1f}s")
    summary.add_row("Passed:", Text(f"{passed} ({rate:.0f}%)", style="green"))
    summary.add_row("Failed:", Text(str(failed), style="red" if failed else "dim"))
    summary.add_row("Errors:", Text(str(errors), style="yellow" if errors else "dim"))
    summary.add_row(
        "Avg time:", f"{total_duration / total:.1f}s per test" if total else "N/A"
    )

    console.print(
        Panel(
            summary,
            title="[bold]Summary[/bold]",
            border_style="green" if rate == 100 else "yellow",
        )
    )

    # Agent breakdown
    agents = sorted(set(r["agent"] for r in results))
    if len(agents) > 1:
        agent_table = Table(title="By Agent", show_header=True)
        agent_table.add_column("Agent")
        agent_table.add_column("Passed", justify="right")
        agent_table.add_column("Total", justify="right")
        agent_table.add_column("Rate", justify="right")

        for a in agents:
            a_results = [r for r in results if r["agent"] == a]
            a_passed = sum(1 for r in a_results if r["status"] == "PASS")
            a_total = len(a_results)
            a_rate = (a_passed / a_total * 100) if a_total else 0

            rate_style = (
                "green" if a_rate == 100 else "yellow" if a_rate >= 50 else "red"
            )
            agent_table.add_row(
                a,
                str(a_passed),
                str(a_total),
                Text(f"{a_rate:.0f}%", style=rate_style),
            )

        console.print(agent_table)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run demo evaluations")
    parser.add_argument(
        "--agent",
        "-a",
        choices=list(AGENT_TESTS.keys()),
        help="Run tests for a specific agent",
    )
    parser.add_argument(
        "--category", "-c", choices=CATEGORIES, help="Filter by category"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show full responses on failure"
    )
    args = parser.parse_args()

    passed_count, failed_count, error_count = run_evals(
        agent=args.agent, category=args.category, verbose=args.verbose
    )
    raise SystemExit(1 if failed_count > 0 or error_count > 0 else 0)
