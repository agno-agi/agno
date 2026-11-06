"""Narrow manager tools that dispatch accepted work without waiting for its result."""

import json
from typing import Any
from weakref import ref

from agno.company.conversation import (
    aget_conversation_tasks,
    asubmit_company_task,
    get_conversation_tasks,
    submit_company_task,
)
from agno.tools import Toolkit


class CompanyConversationTools(Toolkit):
    def __init__(self, agent_os: Any):
        self._agent_os = ref(agent_os)
        super().__init__(
            name="company_conversation",
            tools=[self.submit_accepted_task, self.get_submitted_tasks],
            async_tools=[
                (self.asubmit_accepted_task, "submit_accepted_task"),
                (self.aget_submitted_tasks, "get_submitted_tasks"),
            ],
            stop_after_tool_call_tools=["submit_accepted_task"],
        )

    def submit_accepted_task(self, task_id: str, run_context: Any) -> str:
        """Submit an already accepted Task; return its identifiers/status immediately and finish this turn."""
        return json.dumps(submit_company_task(self._agent_os(), task_id, run_context))

    async def asubmit_accepted_task(self, task_id: str, run_context: Any) -> str:
        """Submit an already accepted Task; return its identifiers/status immediately and finish this turn."""
        return json.dumps(await asubmit_company_task(self._agent_os(), task_id, run_context))

    def get_submitted_tasks(self, run_context: Any) -> str:
        """Read this caller's conversation Task status and results without waiting for workers."""
        return json.dumps(get_conversation_tasks(self._agent_os(), run_context))

    async def aget_submitted_tasks(self, run_context: Any) -> str:
        """Read this caller's conversation Task status and results without waiting for workers."""
        return json.dumps(await aget_conversation_tasks(self._agent_os(), run_context))
