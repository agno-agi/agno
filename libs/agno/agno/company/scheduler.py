"""Company lifecycle checks around the existing scheduler transport."""

from typing import Any, Dict

from agno.company.execution import _call
from agno.company.review_lock import _active_review, _claim_review, _record_review_run, _release_rejected_review
from agno.db.schemas.scheduler import Schedule
from agno.scheduler.executor import ScheduleExecutor


class CompanyScheduleExecutor(ScheduleExecutor):
    def __init__(self, *, company_db: Any, schedule_db: Any, queue_store: Any = None, **kwargs: Any):
        super().__init__(**kwargs)
        self.company_db = company_db
        self.schedule_db = schedule_db
        self.queue_store = queue_store

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
        product_id = (schedule.payload or {}).get("metadata", {}).get("product_id")
        if schedule.managed_by != "company" or not product_id:
            return await super()._call_endpoint(schedule)
        claim = await _claim_review(self, schedule, product_id)
        token = _active_review.set(claim)
        try:
            result = await super()._call_endpoint(schedule)
            # A rejected submission cannot still be writing. Unknown transport outcomes retain
            # the reservation: elapsed time alone is never proof that a review has stopped.
            if not result.get("run_id") and 400 <= (result.get("status_code") or 0) < 500:
                await _release_rejected_review()
            return result
        except Exception as exc:
            import httpx

            # These failures occur before HTTP submission, so no executor can have started.
            active = _active_review.get()
            if (
                active
                and not active[2].get("run_id")
                and isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout))
            ):
                await _release_rejected_review()
            raise
        finally:
            _active_review.reset(token)

    async def _poll_run(
        self,
        client: Any,
        headers: Dict[str, str],
        resource_type: str,
        resource_id: str,
        run_id: str,
        session_id: str,
        timeout_seconds: int,
    ) -> Dict[str, Any]:
        await _record_review_run(run_id, session_id)
        return await super()._poll_run(client, headers, resource_type, resource_id, run_id, session_id, timeout_seconds)
