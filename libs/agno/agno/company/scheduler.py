"""Company lifecycle checks around the existing scheduler transport."""

from typing import Any, Dict

from agno.company.execution import _call
from agno.db.schemas.scheduler import Schedule
from agno.scheduler.executor import ScheduleExecutor


class CompanyScheduleExecutor(ScheduleExecutor):
    def __init__(self, *, company_db: Any, schedule_db: Any, **kwargs: Any):
        super().__init__(**kwargs)
        self.company_db = company_db
        self.schedule_db = schedule_db

    async def _call_endpoint(self, schedule: Schedule) -> Dict[str, Any]:
        from agno.company.routines import _require_active_routine_product

        if schedule.managed_by == "company":
            try:
                await _require_active_routine_product(
                    self.company_db, (schedule.payload or {}).get("metadata", {}).get("product_id")
                )
            except ValueError:
                await _call(
                    self.schedule_db,
                    "update_schedule",
                    schedule.id,
                    enabled=False,
                    disabled_reason="company_product_archived",
                )
                raise
        return await super()._call_endpoint(schedule)
