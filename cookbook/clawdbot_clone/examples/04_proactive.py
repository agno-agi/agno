"""
Proactive Features Example - Clawdbot Clone

Demonstrates the scheduler for:
- Morning briefings
- Reminders
- Scheduled tasks

This is one of Clawdbot's key differentiators - an AI that reaches out to YOU.

Usage:
    .venvs/demo/bin/python cookbook/clawdbot_clone/examples/04_proactive.py
"""

import asyncio
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from cookbook.clawdbot_clone import ClawdbotConfig, create_clawdbot
from cookbook.clawdbot_clone.proactive import ProactiveScheduler, Reminder, ScheduledTask

# Configuration
config = ClawdbotConfig(
    bot_name="Jarvis",
    use_sqlite=True,
    sqlite_path="tmp/clawdbot_proactive.db",
    timezone="UTC",  # Change to your timezone
)

# Create the agent
agent = create_clawdbot(config)


# Callback to send messages (in a real app, this would send to Discord/Telegram)
async def send_message(user_id: str, message: str):
    print(f"\n[PROACTIVE MESSAGE to {user_id}]")
    print("-" * 40)
    print(message)
    print("-" * 40)
    print()


async def main():
    print("=" * 60)
    print("Clawdbot Clone - Proactive Features Demo")
    print("=" * 60)
    print()

    # Create scheduler
    scheduler = ProactiveScheduler(
        agent=agent,
        timezone=config.timezone,
        send_callback=send_message,
    )

    # Add a reminder for 10 seconds from now
    tz = ZoneInfo(config.timezone)
    now = datetime.now(tz)

    print("Setting up proactive features...")
    print()

    # Add a quick reminder (10 seconds from now for demo)
    reminder = Reminder(
        user_id="demo_user",
        message="This is a test reminder! The proactive system is working.",
        remind_at=now + timedelta(seconds=10),
    )
    scheduler.add_reminder(reminder)
    print(f"Added reminder for {reminder.remind_at.strftime('%H:%M:%S')}")

    # Add a recurring check-in task (every 30 seconds for demo)
    check_in_count = 0

    async def periodic_check():
        nonlocal check_in_count
        check_in_count += 1
        return f"Periodic check-in #{check_in_count}: Everything is running smoothly!"

    scheduler.add_task(
        ScheduledTask(
            name="periodic_check",
            callback=periodic_check,
            interval_minutes=0.5,  # 30 seconds for demo
            context={"user_id": "demo_user"},
        )
    )
    print("Added periodic check-in task (every 30 seconds)")

    # Add morning briefing (commented out - would run at specified time)
    # scheduler.add_morning_briefing(
    #     briefing_time=time(8, 0),
    #     user_id="demo_user",
    # )
    # print(f"Added morning briefing at 08:00 {config.timezone}")

    print()
    print("Starting scheduler...")
    print("Watch for proactive messages below.")
    print("Press Ctrl+C to stop.")
    print()

    # Start the scheduler
    scheduler.start()

    # Also allow interactive chat while scheduler runs
    try:
        while True:
            # Simple async input
            user_input = await asyncio.get_event_loop().run_in_executor(
                None, lambda: input("You (or wait for proactive messages): ").strip()
            )

            if user_input.lower() in ("quit", "exit"):
                break

            if user_input:
                response = await agent.arun(
                    input=user_input,
                    user_id="demo_user",
                    session_id="proactive_demo",
                )
                print(f"\nJarvis: {response.content}\n")

    except KeyboardInterrupt:
        print("\n\nShutting down...")

    # Stop scheduler
    await scheduler.stop_async()
    print("Scheduler stopped. Goodbye!")


if __name__ == "__main__":
    asyncio.run(main())
