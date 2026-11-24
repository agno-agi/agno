"""Company lifecycle checks around the existing scheduler transport."""

from typing import Any, Dict

from agno.company.execution import _call
from agno.db.schemas.scheduler import Schedule
from agno.exceptions import MigrationRequiredError
from agno.scheduler.executor import ScheduleExecutor, _preserve_updated_at


class CompanyScheduleExecutor(ScheduleExecutor):
    def __init__(self, *, company_db: Any, schedule_db: Any, **kwargs: Any):
        super().__init__(**kwargs)
        self.company_db = company_db
        self.schedule_db = schedule_db

    async def _call_endpoint(self, schedule: Schedule) -> Dict[str, Any]:
        from agno.company.routines import _require_active_routine_goal

        if schedule.managed_by == "company":
            metadata = (schedule.payload or {}).get("metadata", {})
            if "goal_id" not in metadata and "product_id" in metadata:
                # Not migrated yet: fail this run and leave the Routine enabled for the next one.
                raise MigrationRequiredError(
                    table_name=self.schedule_db.schedules_table_name,
                    message=(
                        f"Routine {schedule.id} was saved by an older version of Agno. Apply the pending migrations "
                        "to the database that holds the schedules with `asyncio.run(MigrationManager(db).up())` "
                        "(import it from `agno.db.migrations.manager`)."
                    ),
                )
            try:
                await _require_active_routine_goal(self.company_db, metadata.get("goal_id"))
            except ValueError:
                await _call(
                    self.schedule_db,
                    "update_schedule",
                    schedule.id,
                    enabled=False,
                    disabled_reason="company_goal_archived",
                    **_preserve_updated_at(self.schedule_db, "update_schedule", schedule),
                )
                raise
        return await super()._call_endpoint(schedule)
