"""
Proactive Scheduler for Clawdbot Clone.

Enables scheduled tasks, reminders, and proactive outreach.
This is one of Clawdbot's key differentiators - an AI that reaches out to YOU.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from agno.agent import Agent
from agno.utils.log import log_info, log_warning


@dataclass
class ScheduledTask:
    """A task scheduled to run at a specific time or interval."""

    name: str
    callback: Callable[..., Any]
    schedule_time: Optional[time] = None  # Daily at this time
    interval_minutes: Optional[int] = None  # Every N minutes
    enabled: bool = True
    last_run: Optional[datetime] = None
    context: dict = field(default_factory=dict)


@dataclass
class Reminder:
    """A reminder for the user."""

    user_id: str
    message: str
    remind_at: datetime
    created_at: datetime = field(default_factory=datetime.now)
    completed: bool = False
    recurring: Optional[str] = None  # "daily", "weekly", None


class ProactiveScheduler:
    """
    Scheduler for proactive AI capabilities.

    Enables:
    - Morning briefings
    - Scheduled reminders
    - Periodic check-ins
    - Event-driven notifications
    """

    def __init__(
        self,
        agent: Agent,
        timezone: str = "UTC",
        send_callback: Optional[Callable[[str, str], Any]] = None,
    ):
        """
        Initialize the scheduler.

        Args:
            agent: The Clawdbot agent
            timezone: Timezone for scheduling
            send_callback: Function to send messages to users (platform-specific)
        """
        self.agent = agent
        self.timezone = ZoneInfo(timezone)
        self.send_callback = send_callback
        self.tasks: list[ScheduledTask] = []
        self.reminders: list[Reminder] = []
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def add_task(self, task: ScheduledTask) -> None:
        """Add a scheduled task."""
        self.tasks.append(task)
        log_info(f"Added scheduled task: {task.name}")

    def add_reminder(self, reminder: Reminder) -> None:
        """Add a reminder."""
        self.reminders.append(reminder)
        log_info(f"Added reminder for user {reminder.user_id}: {reminder.message}")

    def add_morning_briefing(
        self,
        briefing_time: time = time(8, 0),
        user_id: str = "default",
    ) -> None:
        """
        Add a daily morning briefing.

        The agent will generate a personalized briefing based on:
        - User's stored memories and preferences
        - Pending reminders
        - Weather (if configured)
        - Calendar events (if configured)
        """

        async def generate_briefing() -> str:
            prompt = """
            Generate a friendly morning briefing for the user.
            Include:
            1. A warm greeting based on the time
            2. Any reminders or tasks you know about
            3. Anything relevant from our past conversations
            Keep it concise and helpful.
            """
            response = await self.agent.arun(
                input=prompt,
                user_id=user_id,
                session_id="morning_briefing",
            )
            return str(response.content) if response.content else "Good morning!"

        task = ScheduledTask(
            name="morning_briefing",
            callback=generate_briefing,
            schedule_time=briefing_time,
            context={"user_id": user_id},
        )
        self.add_task(task)

    async def _check_reminders(self) -> list[Reminder]:
        """Check for due reminders."""
        now = datetime.now(self.timezone)
        due_reminders = []

        for reminder in self.reminders:
            if not reminder.completed and reminder.remind_at <= now:
                due_reminders.append(reminder)
                reminder.completed = True

                # Handle recurring reminders
                if reminder.recurring == "daily":
                    new_reminder = Reminder(
                        user_id=reminder.user_id,
                        message=reminder.message,
                        remind_at=reminder.remind_at + timedelta(days=1),
                        recurring="daily",
                    )
                    self.reminders.append(new_reminder)
                elif reminder.recurring == "weekly":
                    new_reminder = Reminder(
                        user_id=reminder.user_id,
                        message=reminder.message,
                        remind_at=reminder.remind_at + timedelta(weeks=1),
                        recurring="weekly",
                    )
                    self.reminders.append(new_reminder)

        return due_reminders

    async def _check_scheduled_tasks(self) -> list[ScheduledTask]:
        """Check for tasks that should run now."""
        now = datetime.now(self.timezone)
        tasks_to_run = []

        for task in self.tasks:
            if not task.enabled:
                continue

            should_run = False

            # Check daily scheduled time
            if task.schedule_time:
                current_time = now.time()
                if task.last_run is None or task.last_run.date() < now.date():
                    if current_time >= task.schedule_time:
                        should_run = True

            # Check interval
            if task.interval_minutes:
                if task.last_run is None:
                    should_run = True
                else:
                    elapsed = (now - task.last_run).total_seconds() / 60
                    if elapsed >= task.interval_minutes:
                        should_run = True

            if should_run:
                tasks_to_run.append(task)
                task.last_run = now

        return tasks_to_run

    async def _run_loop(self) -> None:
        """Main scheduler loop."""
        log_info("Proactive scheduler started")

        while self._running:
            try:
                # Check reminders
                due_reminders = await self._check_reminders()
                for reminder in due_reminders:
                    if self.send_callback:
                        await self._send_message(
                            reminder.user_id,
                            f"Reminder: {reminder.message}",
                        )
                    log_info(f"Sent reminder to {reminder.user_id}: {reminder.message}")

                # Check scheduled tasks
                tasks_to_run = await self._check_scheduled_tasks()
                for task in tasks_to_run:
                    try:
                        if asyncio.iscoroutinefunction(task.callback):
                            result = await task.callback()
                        else:
                            result = task.callback()

                        if result and self.send_callback:
                            user_id = task.context.get("user_id", "default")
                            await self._send_message(user_id, str(result))

                        log_info(f"Executed scheduled task: {task.name}")
                    except Exception as e:
                        log_warning(f"Error in scheduled task {task.name}: {e}")

                # Sleep before next check
                await asyncio.sleep(60)  # Check every minute

            except asyncio.CancelledError:
                break
            except Exception as e:
                log_warning(f"Error in scheduler loop: {e}")
                await asyncio.sleep(60)

        log_info("Proactive scheduler stopped")

    async def _send_message(self, user_id: str, message: str) -> None:
        """Send a message to a user via the configured callback."""
        if self.send_callback:
            if asyncio.iscoroutinefunction(self.send_callback):
                await self.send_callback(user_id, message)
            else:
                self.send_callback(user_id, message)

    def start(self) -> None:
        """Start the scheduler in the background."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def start_async(self) -> None:
        """Start the scheduler (async version)."""
        self.start()

    def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def stop_async(self) -> None:
        """Stop the scheduler (async version)."""
        self.stop()
        # Wait for the task to complete
        if self._task:
            try:
                await self._task
            except asyncio.CancelledError:
                pass


# Convenience functions for creating reminders from natural language
def parse_reminder_time(text: str, timezone: str = "UTC") -> Optional[datetime]:
    """
    Parse a natural language time into a datetime.

    Examples:
    - "in 5 minutes"
    - "tomorrow at 9am"
    - "next monday"

    Note: For production use, consider using a library like dateparser.
    """
    tz = ZoneInfo(timezone)
    now = datetime.now(tz)

    text = text.lower().strip()

    # Simple patterns
    if text.startswith("in "):
        parts = text[3:].split()
        if len(parts) >= 2:
            try:
                amount = int(parts[0])
                unit = parts[1]
                if "minute" in unit:
                    return now + timedelta(minutes=amount)
                elif "hour" in unit:
                    return now + timedelta(hours=amount)
                elif "day" in unit:
                    return now + timedelta(days=amount)
            except ValueError:
                pass

    if text == "tomorrow":
        return now + timedelta(days=1)

    # For more complex parsing, users should integrate dateparser
    return None
