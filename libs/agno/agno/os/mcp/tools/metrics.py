"""Metrics MCP tools for system analytics."""

from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Optional, cast

from fastmcp import FastMCP

from agno.db.base import AsyncBaseDb
from agno.os.routers.metrics.schemas import DayAggregatedMetrics
from agno.os.utils import get_db

if TYPE_CHECKING:
    from agno.os.app import AgentOS


def register_metrics_tools(mcp: FastMCP, os: "AgentOS") -> None:
    """Register metrics MCP tools."""

    @mcp.tool(
        name="get_metrics",
        description="Get AgentOS metrics and analytics for a specified date range",
        tags={"metrics"},
    )  # type: ignore
    async def get_metrics(
        db_id: Optional[str] = None,
        starting_date: Optional[str] = None,
        ending_date: Optional[str] = None,
    ) -> dict:
        db = await get_db(os.dbs, db_id)

        # Parse date strings if provided
        start_date = date.fromisoformat(starting_date) if starting_date else None
        end_date = date.fromisoformat(ending_date) if ending_date else None

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            metrics_data, latest_updated_at = await db.get_metrics(
                starting_date=start_date, ending_date=end_date
            )
        else:
            metrics_data, latest_updated_at = db.get_metrics(
                starting_date=start_date, ending_date=end_date
            )

        return {
            "metrics": [DayAggregatedMetrics.from_dict(m).model_dump() for m in metrics_data],
            "updated_at": datetime.fromtimestamp(latest_updated_at, tz=timezone.utc).isoformat()
            if latest_updated_at
            else None,
        }

    @mcp.tool(
        name="refresh_metrics",
        description="Manually trigger recalculation of system metrics from raw data",
        tags={"metrics"},
    )  # type: ignore
    async def refresh_metrics(db_id: Optional[str] = None) -> dict:
        db = await get_db(os.dbs, db_id)

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            result = await db.calculate_metrics()
        else:
            result = db.calculate_metrics()

        if result is None:
            return {"metrics": [], "message": "No metrics to calculate"}

        return {
            "metrics": [DayAggregatedMetrics.from_dict(m).model_dump() for m in result],
            "message": "Metrics refreshed successfully",
        }

