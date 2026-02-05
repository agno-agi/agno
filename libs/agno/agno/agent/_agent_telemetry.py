from __future__ import annotations

from typing import (
    Any,
    Dict,
    Optional,
)

from agno.agent._agent_facet_base import AgentFacetBase
from agno.utils.log import (
    log_debug,
)


class AgentTelemetryFacet(AgentFacetBase):
    ###########################################################################
    # Api functions
    ###########################################################################

    def _get_telemetry_data(self) -> Dict[str, Any]:
        """Get the telemetry data for the agent"""
        return {
            "agent_id": self.id,
            "db_type": self.db.__class__.__name__ if self.db else None,
            "model_provider": self.model.provider if self.model else None,
            "model_name": self.model.name if self.model else None,
            "model_id": self.model.id if self.model else None,
            "parser_model": self.parser_model.to_dict() if self.parser_model else None,
            "output_model": self.output_model.to_dict() if self.output_model else None,
            "has_tools": self.tools is not None,
            "has_memory": self.update_memory_on_run is True
            or self.enable_agentic_memory is True
            or self.memory_manager is not None,
            "has_learnings": self._learning is not None,
            "has_culture": self.enable_agentic_culture is True
            or self.update_cultural_knowledge is True
            or self.culture_manager is not None,
            "has_reasoning": self.reasoning is True,
            "has_knowledge": self.knowledge is not None,
            "has_input_schema": self.input_schema is not None,
            "has_output_schema": self.output_schema is not None,
            "has_team": self.team_id is not None,
        }

    def _log_agent_telemetry(self, session_id: str, run_id: Optional[str] = None) -> None:
        """Send a telemetry event to the API for a created Agent run"""

        self._set_telemetry()
        if not self.telemetry:
            return

        from agno.api.agent import AgentRunCreate, create_agent_run

        try:
            create_agent_run(
                run=AgentRunCreate(
                    session_id=session_id,
                    run_id=run_id,
                    data=self._get_telemetry_data(),
                ),
            )
        except Exception as e:
            log_debug(f"Could not create Agent run telemetry event: {e}")

    async def _alog_agent_telemetry(self, session_id: str, run_id: Optional[str] = None) -> None:
        """Send a telemetry event to the API for a created Agent async run"""

        self._set_telemetry()
        if not self.telemetry:
            return

        from agno.api.agent import AgentRunCreate, acreate_agent_run

        try:
            await acreate_agent_run(
                run=AgentRunCreate(
                    session_id=session_id,
                    run_id=run_id,
                    data=self._get_telemetry_data(),
                )
            )

        except Exception as e:
            log_debug(f"Could not create Agent run telemetry event: {e}")
