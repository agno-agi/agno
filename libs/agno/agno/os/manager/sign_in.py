"""Super Agent's tools to sign a Codex agent in to a ChatGPT subscription with a device code.

A person says "sign in codex-1" in chat. The tool starts the sign-in and gives back a link and a
short code; the person opens the link in their own browser and enters the code there. Only an
administrator may do this: the agent then works on that person's subscription. The sign-in
itself never reaches the model: a tool returns the link, the code and a status.
"""

import json
from typing import Any, Dict, Optional
from weakref import ReferenceType, ref

from agno.tools import Toolkit

SIGN_IN_INSTRUCTIONS = """\
Signing a Codex agent in to ChatGPT: when a person asks to sign in or connect a Codex agent, call
start_agent_sign_in and give them the link and the code exactly as returned. They enter the code
themselves, in their own browser; never ask them to send it back or to send any password. Then
call check_agent_sign_in when they say they are done, and tell them the status it returns.
"""


class SignInTools(Toolkit):
    """start_agent_sign_in and check_agent_sign_in, for the Codex agents this AgentOS serves."""

    def __init__(self, agent_os: Any, **kwargs: Any):
        super().__init__(name="sign_in_tools", **kwargs)
        self._agent_os: ReferenceType[Any] = ref(agent_os)
        self.register(self.start_agent_sign_in)
        self.register(self.astart_agent_sign_in, name="start_agent_sign_in")
        self.register(self.check_agent_sign_in)
        self.register(self.acheck_agent_sign_in, name="check_agent_sign_in")

    def _codex_agent(self, agent_id: str) -> Any:
        from agno.agents.codex import CodexAgent
        from agno.os.utils import get_agent_by_id

        agent_os: Any = self._agent_os()
        agent = get_agent_by_id(
            agent_id=agent_id, agents=agent_os.agents, db=agent_os.db, registry=agent_os.registry, published_only=False
        )
        if not isinstance(agent, CodexAgent):
            raise ValueError(f"{agent_id} is not a Codex agent this AgentOS serves; only a Codex agent signs in")
        return agent

    def _authority(self, run_context: Any) -> Any:
        """The chatting person's authority. Raises PermissionError for an automated run or no person."""
        from agno.os.auth import _authorization_enforced
        from agno.tools.company import _authority, _require_human_creation

        _require_human_creation(run_context, "sign an agent in")
        authority = _authority(run_context)
        agent_os = self._agent_os()
        app = getattr(agent_os, "_manager_app", None)
        if authority is None and (bool(getattr(agent_os, "authorization", None)) or _authorization_enforced(app)):
            raise PermissionError("A signed-in administrator is required to sign an agent in")
        return authority

    @staticmethod
    def _refusal(error: Exception) -> str:
        return json.dumps({"error": str(error) or type(error).__name__})

    def start_agent_sign_in(self, agent_id: str, _agno_run_context: Optional[Any] = None) -> str:
        """Start a ChatGPT sign-in for a Codex agent. Returns the link to open and the code to enter there.

        Args:
            agent_id (str): The Codex agent to sign in, such as codex-1.
        """
        try:
            authority = self._authority(_agno_run_context)
            if authority is not None:
                authority.require("agent_os", "admin")
            started: Dict[str, Any] = self._codex_agent(agent_id).sign_in()
        except (PermissionError, ValueError, ImportError, RuntimeError) as error:
            return self._refusal(error)
        return json.dumps(started)

    async def astart_agent_sign_in(self, agent_id: str, _agno_run_context: Optional[Any] = None) -> str:
        """Start a ChatGPT sign-in for a Codex agent. Returns the link to open and the code to enter there.

        Args:
            agent_id (str): The Codex agent to sign in, such as codex-1.
        """
        try:
            authority = self._authority(_agno_run_context)
            if authority is not None:
                await authority.arequire("agent_os", "admin")
            started: Dict[str, Any] = await self._codex_agent(agent_id).asign_in()
        except (PermissionError, ValueError, ImportError, RuntimeError) as error:
            return self._refusal(error)
        return json.dumps(started)

    def check_agent_sign_in(self, agent_id: str, _agno_run_context: Optional[Any] = None) -> str:
        """Read where a Codex agent's ChatGPT sign-in stands: waiting, signed_in, failed or not_signed_in.

        Args:
            agent_id (str): The Codex agent, such as codex-1.
        """
        try:
            authority = self._authority(_agno_run_context)
            if authority is not None:
                authority.require("agent_os", "admin")
            status: Dict[str, Any] = self._codex_agent(agent_id).sign_in_status()
        except (PermissionError, ValueError, ImportError, RuntimeError) as error:
            return self._refusal(error)
        return json.dumps(status)

    async def acheck_agent_sign_in(self, agent_id: str, _agno_run_context: Optional[Any] = None) -> str:
        """Read where a Codex agent's ChatGPT sign-in stands: waiting, signed_in, failed or not_signed_in.

        Args:
            agent_id (str): The Codex agent, such as codex-1.
        """
        try:
            authority = self._authority(_agno_run_context)
            if authority is not None:
                await authority.arequire("agent_os", "admin")
            status: Dict[str, Any] = await self._codex_agent(agent_id).asign_in_status()
        except (PermissionError, ValueError, ImportError, RuntimeError) as error:
            return self._refusal(error)
        return json.dumps(status)
