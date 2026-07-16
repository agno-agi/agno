"""SchedulerTools -- give agents the ability to create and manage recurring schedules.

Wraps the ScheduleManager to expose schedule CRUD as agent-callable tools.
Requires a database backend that implements the scheduler DB methods and
the AgentOS server + SchedulePoller to actually execute the schedules.

Example:
    from agno.tools.scheduler import SchedulerTools

    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[
            SchedulerTools(
                db=scheduler_db,
                default_endpoint="/agents/my-agent/runs",
            )
        ],
    )
"""

import json
from typing import Any, Callable, Dict, List, Optional

from agno.scheduler.manager import ScheduleManager
from agno.tools.toolkit import Toolkit
from agno.utils.log import log_debug, logger


class SchedulerTools(Toolkit):
    """Toolkit that lets an agent create and manage recurring schedules.

    The agent can ask a user "what should I do every day?" and then call
    ``create_schedule`` to set up a cron-based recurring execution via the
    existing AgentOS scheduler infrastructure.

    Args:
        db: A database adapter that implements the scheduler DB methods.
        default_endpoint: The default endpoint to call when a schedule fires
            (e.g. ``/agents/<agent_id>/runs``). The agent can override this
            per-schedule, but having a default simplifies the common case.
        default_method: HTTP method for the endpoint (default: ``POST``).
        default_timezone: Default timezone for schedules (default: ``UTC``).
        default_payload: Default payload to send with each scheduled run.
            The agent can override or extend this per-schedule.
    """

    def __init__(
        self,
        db: Any,
        default_endpoint: Optional[str] = None,
        default_method: str = "POST",
        default_timezone: str = "UTC",
        default_payload: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ):
        self.manager = ScheduleManager(db=db)
        self.default_endpoint = default_endpoint
        self.default_method = default_method
        self.default_timezone = default_timezone
        self.default_payload = default_payload

        tools: List[Callable] = [
            self.create_schedule,
            self.list_schedules,
            self.get_schedule,
            self.delete_schedule,
            self.enable_schedule,
            self.disable_schedule,
            self.get_schedule_runs,
        ]

        async_tools: List[tuple[Callable[..., Any], str]] = [
            (self.acreate_schedule, "create_schedule"),
            (self.alist_schedules, "list_schedules"),
            (self.aget_schedule, "get_schedule"),
            (self.adelete_schedule, "delete_schedule"),
            (self.aenable_schedule, "enable_schedule"),
            (self.adisable_schedule, "disable_schedule"),
            (self.aget_schedule_runs, "get_schedule_runs"),
        ]

        super().__init__(
            name="scheduler",
            tools=tools,
            async_tools=async_tools,
            instructions=(
                "Use these tools to create and manage recurring scheduled tasks. "
                "When a user asks you to do something on a recurring basis (daily, weekly, etc.), "
                "convert their request into a cron expression and create a schedule. "
                "Common cron patterns: '0 9 * * *' (daily at 9am), '0 9 * * 1' (every Monday at 9am), "
                "'0 */6 * * *' (every 6 hours), '0 9 * * 1-5' (weekdays at 9am). "
                "When creating schedules for run endpoints (ending in /runs), you MUST include a "
                '\'message\' field in the payload, e.g. {"message": "Run the daily health check"}.'
            ),
            **kwargs,
        )

    @staticmethod
    def _is_run_endpoint(endpoint: str, method: str) -> bool:
        """Check if the endpoint targets an agent/team/workflow run route."""
        return method.upper() == "POST" and endpoint.rstrip("/").endswith("/runs")

    # ------------------------------------------------------------------
    # Sync tools
    # ------------------------------------------------------------------

    def create_schedule(
        self,
        name: str,
        cron: str,
        description: Optional[str] = None,
        endpoint: Optional[str] = None,
        method: Optional[str] = None,
        payload: Optional[str] = None,
        timezone: Optional[str] = None,
    ) -> str:
        """Create a new recurring schedule that runs on a cron expression.

        Args:
            name (str): A unique name for the schedule (e.g. "daily-weather-report").
            cron (str): A 5-field cron expression (e.g. "0 9 * * *" for daily at 9am UTC).
            description (str): A human-readable description of what this schedule does.
            endpoint (str): The API endpoint to call when the schedule fires. Uses the default if not provided.
            method (str): HTTP method (GET, POST, etc.). Uses the default if not provided.
            payload (str): JSON string of the payload to send with the request. Uses the default if not provided.
            timezone (str): Timezone for the cron expression (e.g. "America/New_York"). Uses the default if not provided.

        Returns:
            str: JSON string with the created schedule details.
        """
        resolved_endpoint = endpoint or self.default_endpoint
        if not resolved_endpoint:
            return json.dumps({"error": "No endpoint provided and no default_endpoint configured"})

        resolved_payload = self.default_payload
        if payload is not None:
            try:
                resolved_payload = json.loads(payload)
            except json.JSONDecodeError:
                return json.dumps({"error": "Invalid JSON in payload parameter"})

        # Run endpoints require a "message" field in the payload
        resolved_method = method or self.default_method
        if self._is_run_endpoint(resolved_endpoint, resolved_method):
            if not resolved_payload or "message" not in resolved_payload:
                return json.dumps(
                    {
                        "error": "Schedules targeting run endpoints require a 'message' field in the payload. "
                        'Provide payload with at least: {"message": "your prompt here"}'
                    }
                )

        try:
            schedule = self.manager.create(
                name=name,
                cron=cron,
                endpoint=resolved_endpoint,
                method=resolved_method,
                description=description,
                payload=resolved_payload,
                timezone=timezone or self.default_timezone,
                if_exists="update",
            )
            log_debug(f"Schedule created: {schedule.name} ({schedule.cron_expr})")
            return json.dumps(
                {
                    "status": "created",
                    "id": schedule.id,
                    "name": schedule.name,
                    "cron": schedule.cron_expr,
                    "endpoint": schedule.endpoint,
                    "timezone": schedule.timezone,
                    "enabled": schedule.enabled,
                    "description": schedule.description,
                }
            )
        except Exception as e:
            logger.exception("Failed to create schedule")
            return json.dumps({"error": str(e)})

    def list_schedules(self, enabled_only: bool = False) -> str:
        """List all existing schedules.

        Args:
            enabled_only (bool): If True, only return enabled schedules. Defaults to False.

        Returns:
            str: JSON string with the list of schedules.
        """
        try:
            enabled_filter = True if enabled_only else None
            schedules = self.manager.list(enabled=enabled_filter)
            result = [
                {
                    "id": s.id,
                    "name": s.name,
                    "cron": s.cron_expr,
                    "endpoint": s.endpoint,
                    "timezone": s.timezone,
                    "enabled": s.enabled,
                    "description": s.description,
                }
                for s in schedules
            ]
            return json.dumps({"schedules": result, "count": len(result)})
        except Exception as e:
            logger.exception("Failed to list schedules")
            return json.dumps({"error": str(e)})

    def get_schedule(self, schedule_id: str) -> str:
        """Get details of a specific schedule by its ID.

        Args:
            schedule_id (str): The ID of the schedule to retrieve.

        Returns:
            str: JSON string with the schedule details.
        """
        try:
            schedule = self.manager.get(schedule_id)
            if schedule is None:
                return json.dumps({"error": f"Schedule not found: {schedule_id}"})
            return json.dumps(
                {
                    "id": schedule.id,
                    "name": schedule.name,
                    "cron": schedule.cron_expr,
                    "endpoint": schedule.endpoint,
                    "method": schedule.method,
                    "timezone": schedule.timezone,
                    "enabled": schedule.enabled,
                    "description": schedule.description,
                    "payload": schedule.payload,
                }
            )
        except Exception as e:
            logger.exception("Failed to get schedule")
            return json.dumps({"error": str(e)})

    def delete_schedule(self, schedule_id: str) -> str:
        """Delete a schedule by its ID. This permanently removes the schedule.

        Args:
            schedule_id (str): The ID of the schedule to delete.

        Returns:
            str: JSON string confirming deletion.
        """
        try:
            deleted = self.manager.delete(schedule_id)
            if deleted:
                return json.dumps({"status": "deleted", "id": schedule_id})
            return json.dumps({"error": f"Schedule not found or could not be deleted: {schedule_id}"})
        except Exception as e:
            logger.exception("Failed to delete schedule")
            return json.dumps({"error": str(e)})

    def enable_schedule(self, schedule_id: str) -> str:
        """Enable a disabled schedule so it starts running again.

        Args:
            schedule_id (str): The ID of the schedule to enable.

        Returns:
            str: JSON string with the updated schedule details.
        """
        try:
            schedule = self.manager.enable(schedule_id)
            if schedule is None:
                return json.dumps({"error": f"Schedule not found: {schedule_id}"})
            return json.dumps(
                {
                    "status": "enabled",
                    "id": schedule.id,
                    "name": schedule.name,
                    "enabled": schedule.enabled,
                }
            )
        except Exception as e:
            logger.exception("Failed to enable schedule")
            return json.dumps({"error": str(e)})

    def disable_schedule(self, schedule_id: str) -> str:
        """Disable a schedule so it stops running. Can be re-enabled later.

        Args:
            schedule_id (str): The ID of the schedule to disable.

        Returns:
            str: JSON string with the updated schedule details.
        """
        try:
            schedule = self.manager.disable(schedule_id)
            if schedule is None:
                return json.dumps({"error": f"Schedule not found: {schedule_id}"})
            return json.dumps(
                {
                    "status": "disabled",
                    "id": schedule.id,
                    "name": schedule.name,
                    "enabled": schedule.enabled,
                }
            )
        except Exception as e:
            logger.exception("Failed to disable schedule")
            return json.dumps({"error": str(e)})

    def get_schedule_runs(self, schedule_id: str, limit: int = 10) -> str:
        """Get the run history for a schedule.

        Args:
            schedule_id (str): The ID of the schedule to get runs for.
            limit (int): Maximum number of runs to return. Defaults to 10.

        Returns:
            str: JSON string with the list of runs.
        """
        try:
            runs = self.manager.get_runs(schedule_id, limit=limit)
            result = [
                {
                    "id": r.id,
                    "status": r.status,
                    "triggered_at": r.triggered_at,
                    "completed_at": r.completed_at,
                    "error": r.error,
                }
                for r in runs
            ]
            return json.dumps({"runs": result, "count": len(result)})
        except Exception as e:
            logger.exception("Failed to get schedule runs")
            return json.dumps({"error": str(e)})

    # ------------------------------------------------------------------
    # Async tools
    # ------------------------------------------------------------------

    async def acreate_schedule(
        self,
        name: str,
        cron: str,
        description: Optional[str] = None,
        endpoint: Optional[str] = None,
        method: Optional[str] = None,
        payload: Optional[str] = None,
        timezone: Optional[str] = None,
    ) -> str:
        """Create a new recurring schedule that runs on a cron expression.

        Args:
            name (str): A unique name for the schedule (e.g. "daily-weather-report").
            cron (str): A 5-field cron expression (e.g. "0 9 * * *" for daily at 9am UTC).
            description (str): A human-readable description of what this schedule does.
            endpoint (str): The API endpoint to call when the schedule fires. Uses the default if not provided.
            method (str): HTTP method (GET, POST, etc.). Uses the default if not provided.
            payload (str): JSON string of the payload to send with the request. Uses the default if not provided.
            timezone (str): Timezone for the cron expression (e.g. "America/New_York"). Uses the default if not provided.

        Returns:
            str: JSON string with the created schedule details.
        """
        resolved_endpoint = endpoint or self.default_endpoint
        if not resolved_endpoint:
            return json.dumps({"error": "No endpoint provided and no default_endpoint configured"})

        resolved_payload = self.default_payload
        if payload is not None:
            try:
                resolved_payload = json.loads(payload)
            except json.JSONDecodeError:
                return json.dumps({"error": "Invalid JSON in payload parameter"})

        # Run endpoints require a "message" field in the payload
        resolved_method = method or self.default_method
        if self._is_run_endpoint(resolved_endpoint, resolved_method):
            if not resolved_payload or "message" not in resolved_payload:
                return json.dumps(
                    {
                        "error": "Schedules targeting run endpoints require a 'message' field in the payload. "
                        'Provide payload with at least: {"message": "your prompt here"}'
                    }
                )

        try:
            schedule = await self.manager.acreate(
                name=name,
                cron=cron,
                endpoint=resolved_endpoint,
                method=resolved_method,
                description=description,
                payload=resolved_payload,
                timezone=timezone or self.default_timezone,
                if_exists="update",
            )
            log_debug(f"Schedule created: {schedule.name} ({schedule.cron_expr})")
            return json.dumps(
                {
                    "status": "created",
                    "id": schedule.id,
                    "name": schedule.name,
                    "cron": schedule.cron_expr,
                    "endpoint": schedule.endpoint,
                    "timezone": schedule.timezone,
                    "enabled": schedule.enabled,
                    "description": schedule.description,
                }
            )
        except Exception as e:
            logger.exception("Failed to create schedule")
            return json.dumps({"error": str(e)})

    async def alist_schedules(self, enabled_only: bool = False) -> str:
        """List all existing schedules.

        Args:
            enabled_only (bool): If True, only return enabled schedules. Defaults to False.

        Returns:
            str: JSON string with the list of schedules.
        """
        try:
            enabled_filter = True if enabled_only else None
            schedules = await self.manager.alist(enabled=enabled_filter)
            result = [
                {
                    "id": s.id,
                    "name": s.name,
                    "cron": s.cron_expr,
                    "endpoint": s.endpoint,
                    "timezone": s.timezone,
                    "enabled": s.enabled,
                    "description": s.description,
                }
                for s in schedules
            ]
            return json.dumps({"schedules": result, "count": len(result)})
        except Exception as e:
            logger.exception("Failed to list schedules")
            return json.dumps({"error": str(e)})

    async def aget_schedule(self, schedule_id: str) -> str:
        """Get details of a specific schedule by its ID.

        Args:
            schedule_id (str): The ID of the schedule to retrieve.

        Returns:
            str: JSON string with the schedule details.
        """
        try:
            schedule = await self.manager.aget(schedule_id)
            if schedule is None:
                return json.dumps({"error": f"Schedule not found: {schedule_id}"})
            return json.dumps(
                {
                    "id": schedule.id,
                    "name": schedule.name,
                    "cron": schedule.cron_expr,
                    "endpoint": schedule.endpoint,
                    "method": schedule.method,
                    "timezone": schedule.timezone,
                    "enabled": schedule.enabled,
                    "description": schedule.description,
                    "payload": schedule.payload,
                }
            )
        except Exception as e:
            logger.exception("Failed to get schedule")
            return json.dumps({"error": str(e)})

    async def adelete_schedule(self, schedule_id: str) -> str:
        """Delete a schedule by its ID. This permanently removes the schedule.

        Args:
            schedule_id (str): The ID of the schedule to delete.

        Returns:
            str: JSON string confirming deletion.
        """
        try:
            deleted = await self.manager.adelete(schedule_id)
            if deleted:
                return json.dumps({"status": "deleted", "id": schedule_id})
            return json.dumps({"error": f"Schedule not found or could not be deleted: {schedule_id}"})
        except Exception as e:
            logger.exception("Failed to delete schedule")
            return json.dumps({"error": str(e)})

    async def aenable_schedule(self, schedule_id: str) -> str:
        """Enable a disabled schedule so it starts running again.

        Args:
            schedule_id (str): The ID of the schedule to enable.

        Returns:
            str: JSON string with the updated schedule details.
        """
        try:
            schedule = await self.manager.aenable(schedule_id)
            if schedule is None:
                return json.dumps({"error": f"Schedule not found: {schedule_id}"})
            return json.dumps(
                {
                    "status": "enabled",
                    "id": schedule.id,
                    "name": schedule.name,
                    "enabled": schedule.enabled,
                }
            )
        except Exception as e:
            logger.exception("Failed to enable schedule")
            return json.dumps({"error": str(e)})

    async def adisable_schedule(self, schedule_id: str) -> str:
        """Disable a schedule so it stops running. Can be re-enabled later.

        Args:
            schedule_id (str): The ID of the schedule to disable.

        Returns:
            str: JSON string with the updated schedule details.
        """
        try:
            schedule = await self.manager.adisable(schedule_id)
            if schedule is None:
                return json.dumps({"error": f"Schedule not found: {schedule_id}"})
            return json.dumps(
                {
                    "status": "disabled",
                    "id": schedule.id,
                    "name": schedule.name,
                    "enabled": schedule.enabled,
                }
            )
        except Exception as e:
            logger.exception("Failed to disable schedule")
            return json.dumps({"error": str(e)})

    async def aget_schedule_runs(self, schedule_id: str, limit: int = 10) -> str:
        """Get the run history for a schedule.

        Args:
            schedule_id (str): The ID of the schedule to get runs for.
            limit (int): Maximum number of runs to return. Defaults to 10.

        Returns:
            str: JSON string with the list of runs.
        """
        try:
            runs = await self.manager.aget_runs(schedule_id, limit=limit)
            result = [
                {
                    "id": r.id,
                    "status": r.status,
                    "triggered_at": r.triggered_at,
                    "completed_at": r.completed_at,
                    "error": r.error,
                }
                for r in runs
            ]
            return json.dumps({"runs": result, "count": len(result)})
        except Exception as e:
            logger.exception("Failed to get schedule runs")
            return json.dumps({"error": str(e)})
