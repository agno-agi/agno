"""Telemetry payload generation and logging trait for Team."""

from __future__ import annotations

from typing import (
    Any,
    Dict,
    Optional,
)

from agno.team.trait.base import TeamTraitBase
from agno.utils.log import (
    log_debug,
)


class TeamTelemetryTrait(TeamTraitBase):
    def _get_team_data(self) -> Dict[str, Any]:
        team_data: Dict[str, Any] = {}
        if self.name is not None:
            team_data["name"] = self.name
        if self.id is not None:
            team_data["team_id"] = self.id
        if self.model is not None:
            team_data["model"] = self.model.to_dict()
        return team_data

    def _get_telemetry_data(self) -> Dict[str, Any]:
        """Get the telemetry data for the team"""
        return {
            "team_id": self.id,
            "db_type": self.db.__class__.__name__ if self.db else None,
            "model_provider": self.model.provider if self.model else None,
            "model_name": self.model.name if self.model else None,
            "model_id": self.model.id if self.model else None,
            "parser_model": self.parser_model.to_dict() if self.parser_model else None,
            "output_model": self.output_model.to_dict() if self.output_model else None,
            "member_count": len(self.members) if self.members else 0,
            "has_knowledge": self.knowledge is not None,
            "has_tools": self.tools is not None,
        }

    def _log_team_telemetry(self, session_id: str, run_id: Optional[str] = None) -> None:
        """Send a telemetry event to the API for a created Team run"""

        self._set_telemetry()
        if not self.telemetry:
            return

        from agno.api.team import TeamRunCreate, create_team_run

        try:
            create_team_run(
                run=TeamRunCreate(session_id=session_id, run_id=run_id, data=self._get_telemetry_data()),
            )
        except Exception as e:
            log_debug(f"Could not create Team run telemetry event: {e}")

    async def _alog_team_telemetry(self, session_id: str, run_id: Optional[str] = None) -> None:
        """Send a telemetry event to the API for a created Team async run"""

        self._set_telemetry()
        if not self.telemetry:
            return

        from agno.api.team import TeamRunCreate, acreate_team_run

        try:
            await acreate_team_run(
                run=TeamRunCreate(session_id=session_id, run_id=run_id, data=self._get_telemetry_data())
            )
        except Exception as e:
            log_debug(f"Could not create Team run telemetry event: {e}")
