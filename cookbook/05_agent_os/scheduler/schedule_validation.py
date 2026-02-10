"""Schedule validation and error handling.

This example demonstrates:
- Invalid cron expression handling
- Invalid timezone handling
- Duplicate schedule name handling
- Complex cron patterns (ranges, steps, lists)
- Method auto-uppercasing
"""

from agno.db.sqlite import SqliteDb
from agno.scheduler import ScheduleManager
from agno.scheduler.cli import SchedulerConsole

# --- Setup ---

db = SqliteDb(id="validation-demo", db_file="tmp/validation_demo.db")
mgr = ScheduleManager(db)

# =============================================================================
# 1. Invalid cron expression
# =============================================================================

print("1. Invalid cron expression:")
try:
    mgr.create(name="bad-cron", cron="not valid", endpoint="/test")
except ValueError as e:
    print(f"   Caught ValueError: {e}")

# =============================================================================
# 2. Invalid timezone
# =============================================================================

print("\n2. Invalid timezone:")
try:
    mgr.create(name="bad-tz", cron="0 9 * * *", endpoint="/test", timezone="Fake/Zone")
except ValueError as e:
    print(f"   Caught ValueError: {e}")

# =============================================================================
# 3. Duplicate schedule name
# =============================================================================

print("\n3. Duplicate schedule name:")
s = mgr.create(name="unique-schedule", cron="0 9 * * *", endpoint="/test")
try:
    mgr.create(name="unique-schedule", cron="0 10 * * *", endpoint="/test")
except ValueError as e:
    print(f"   Caught ValueError: {e}")
mgr.delete(s.id)

# =============================================================================
# 4. Complex cron patterns
# =============================================================================

print("\n4. Complex cron patterns:")

# Every 5 minutes
s1 = mgr.create(name="every-5-min", cron="*/5 * * * *", endpoint="/test")
print(f"   */5 * * * * -> Created: {s1.name}")

# Weekdays 9-17
s2 = mgr.create(name="business-hours", cron="0 9-17 * * 1-5", endpoint="/test")
print(f"   0 9-17 * * 1-5 -> Created: {s2.name}")

# First day of month at midnight
s3 = mgr.create(name="monthly-report", cron="0 0 1 * *", endpoint="/test")
print(f"   0 0 1 * * -> Created: {s3.name}")

# =============================================================================
# 5. Method auto-uppercasing
# =============================================================================

print("\n5. Method auto-uppercasing:")
s4 = mgr.create(
    name="lowercase-method", cron="0 9 * * *", endpoint="/test", method="get"
)
print(f"   Input: 'get' -> Stored: '{s4.method}'")

# =============================================================================
# 6. Display all valid schedules
# =============================================================================

print()
console = SchedulerConsole(mgr)
console.show_schedules()

# =============================================================================
# Cleanup
# =============================================================================

for s in [s1, s2, s3, s4]:
    mgr.delete(s.id)
print("All schedules cleaned up.")
