"""Rich CLI console for scheduler -- pretty output for cookbooks."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agno.db.schemas.scheduler import Schedule, ScheduleRun
from agno.scheduler.manager import ScheduleManager


def _ts(epoch: Optional[int]) -> str:
    """Format an epoch timestamp for display."""
    if epoch is None:
        return "-"
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _status_style(status: str) -> str:
    """Return Rich style for a run status."""
    status_upper = status.upper()
    styles = {
        "COMPLETED": "bold green",
        "RUNNING": "bold blue",
        "PENDING": "bold yellow",
        "ERROR": "bold red",
        "CANCELLED": "bold magenta",
        "PAUSED": "bold cyan",
    }
    return styles.get(status_upper, "white")


class SchedulerConsole:
    """Rich-powered display wrapper for ScheduleManager.

    Provides pretty terminal output for schedule CRUD operations,
    designed for use in cookbooks and interactive sessions.
    """

    def __init__(self, manager: ScheduleManager) -> None:
        self.manager = manager

    @classmethod
    def from_db(cls, db: Any) -> "SchedulerConsole":
        """Create a SchedulerConsole from a database instance."""
        return cls(ScheduleManager(db))

    def show_schedules(self, enabled: Optional[bool] = None) -> List[Schedule]:
        """Display all schedules in a Rich table."""
        from rich.console import Console
        from rich.table import Table

        console = Console()
        schedules = self.manager.list(enabled=enabled)

        table = Table(title="Schedules", show_lines=True)
        table.add_column("Name", style="bold cyan")
        table.add_column("Cron", style="white")
        table.add_column("Endpoint", style="white")
        table.add_column("Enabled", justify="center")
        table.add_column("Next Run", style="dim")
        table.add_column("ID", style="dim")

        for s in schedules:
            enabled_str = "[green]Yes[/green]" if s.enabled else "[red]No[/red]"
            table.add_row(
                s.name,
                s.cron_expr,
                f"{s.method} {s.endpoint}",
                enabled_str,
                _ts(s.next_run_at),
                s.id[:8] + "...",
            )

        console.print(table)
        return schedules

    def show_schedule(self, schedule_id: str) -> Optional[Schedule]:
        """Display a single schedule in a Rich panel."""
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table

        console = Console()
        schedule = self.manager.get(schedule_id)
        if schedule is None:
            console.print(f"[red]Schedule not found: {schedule_id}[/red]")
            return None

        info = Table.grid(padding=(0, 2))
        info.add_column(style="bold")
        info.add_column()
        info.add_row("ID:", schedule.id)
        info.add_row("Name:", schedule.name)
        info.add_row("Description:", schedule.description or "-")
        info.add_row("Cron:", schedule.cron_expr)
        info.add_row("Timezone:", schedule.timezone or "UTC")
        info.add_row("Endpoint:", f"{schedule.method} {schedule.endpoint}")
        info.add_row("Enabled:", "[green]Yes[/green]" if schedule.enabled else "[red]No[/red]")
        info.add_row("Next Run:", _ts(schedule.next_run_at))
        info.add_row("Timeout:", f"{schedule.timeout_seconds or 3600}s")
        info.add_row("Max Retries:", str(schedule.max_retries or 0))
        info.add_row("Created:", _ts(schedule.created_at))
        info.add_row("Updated:", _ts(schedule.updated_at))

        console.print(Panel(info, title=f"Schedule: {schedule.name}", border_style="cyan"))
        return schedule

    def show_runs(self, schedule_id: str, limit: int = 20) -> List[ScheduleRun]:
        """Display run history for a schedule in a Rich table."""
        from rich.console import Console
        from rich.table import Table

        console = Console()
        runs = self.manager.get_runs(schedule_id, limit=limit)

        table = Table(title="Schedule Runs", show_lines=True)
        table.add_column("Run ID", style="dim")
        table.add_column("Attempt", justify="center")
        table.add_column("Status")
        table.add_column("Status Code", justify="center")
        table.add_column("Triggered At", style="dim")
        table.add_column("Completed At", style="dim")
        table.add_column("Error", style="red")

        for r in runs:
            status = r.status or "UNKNOWN"
            style = _status_style(status)
            table.add_row(
                r.id[:8] + "...",
                str(r.attempt or 0),
                f"[{style}]{status}[/{style}]",
                str(r.status_code or "-"),
                _ts(r.triggered_at),
                _ts(r.completed_at),
                (r.error or "-")[:60],
            )

        console.print(table)
        return runs

    def create_and_show(
        self,
        name: str,
        cron: str,
        endpoint: str,
        method: str = "POST",
        description: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        timezone: str = "UTC",
        timeout_seconds: int = 3600,
        max_retries: int = 0,
        retry_delay_seconds: int = 60,
        if_exists: str = "raise",
    ) -> Schedule:
        """Create a schedule and display it in a Rich panel."""
        schedule = self.manager.create(
            name=name,
            cron=cron,
            endpoint=endpoint,
            method=method,
            description=description,
            payload=payload,
            timezone=timezone,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_delay_seconds=retry_delay_seconds,
            if_exists=if_exists,
        )
        self.show_schedule(schedule.id)
        return schedule
