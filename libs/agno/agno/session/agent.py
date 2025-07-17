from __future__ import annotations

from dataclasses import asdict, dataclass
from textwrap import dedent
from typing import Any, Dict, List, Mapping, Optional, Type, Union

from pydantic import BaseModel

from agno.models.message import Message
from agno.run.base import RunStatus
from agno.run.response import RunResponse
from agno.session.summary import SessionSummary, SessionSummaryResponse
from agno.utils.log import log_debug, log_warning


@dataclass
class AgentSession:
    """Agent Session that is stored in the database"""

    # Session UUID
    session_id: str
    # ID of the team session this agent session is associated with
    team_session_id: Optional[str] = None

    # ID of the agent that this session is associated with
    agent_id: Optional[str] = None
    # ID of the team that this session is associated with
    team_id: Optional[str] = None
    # # ID of the user interacting with this agent
    user_id: Optional[str] = None
    # ID of the workflow that this session is associated with
    workflow_id: Optional[str] = None

    # Session Data: session_name, session_state, images, videos, audio
    session_data: Optional[Dict[str, Any]] = None
    # Extra Data stored with this agent
    extra_data: Optional[Dict[str, Any]] = None
    # Agent Data: agent_id, name and model
    agent_data: Optional[Dict[str, Any]] = None
    # List of all runs in the session
    runs: Optional[List[RunResponse]] = None
    # Summary of the session
    summary: Optional[SessionSummary] = None

    # The unix timestamp when this session was created
    created_at: Optional[int] = None
    # The unix timestamp when this session was last updated
    updated_at: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        session_dict = asdict(self)

        session_dict["runs"] = [run.to_dict() for run in self.runs] if self.runs else None
        session_dict["summary"] = self.summary.to_dict() if self.summary else None

        return session_dict

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Optional[AgentSession]:
        if data is None or data.get("session_id") is None:
            log_warning("AgentSession is missing session_id")
            return None

        runs = data.get("runs")
        if runs is not None and isinstance(runs[0], dict):
            runs = [RunResponse.from_dict(run) for run in runs]

        summary = data.get("summary")
        if summary is not None and isinstance(summary, dict):
            summary = SessionSummary.from_dict(summary)

        return cls(
            session_id=data.get("session_id"),  # type: ignore
            agent_id=data.get("agent_id"),
            team_session_id=data.get("team_session_id"),
            user_id=data.get("user_id"),
            workflow_id=data.get("workflow_id"),
            team_id=data.get("team_id"),
            agent_data=data.get("agent_data"),
            session_data=data.get("session_data"),
            extra_data=data.get("extra_data"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            runs=runs,
            summary=summary,
        )

    def telemetry_data(self) -> Dict[str, Any]:
        return {
            "model": self.agent_data.get("model") if self.agent_data else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def add_run(self, run: RunResponse):
        """Adds a RunResponse, together with some calculated data, to the runs list."""
        messages = run.messages
        for m in messages:
            if m.metrics is not None:
                m.metrics.timer = None

        if not self.runs:
            self.runs = []

        self.runs.append(run)

        log_debug("Added RunResponse to Agent Session")

    def get_messages_from_last_n_runs(
        self,
        session_id: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        last_n: Optional[int] = None,
        skip_role: Optional[str] = None,
        skip_status: Optional[List[RunStatus]] = None,
        skip_history_messages: bool = True,
    ) -> List[Message]:
        """Returns the messages from the last_n runs, excluding previously tagged history messages.
        Args:
            session_id: The session id to get the messages from.
            agent_id: The id of the agent to get the messages from.
            team_id: The id of the team to get the messages from.
            last_n: The number of runs to return from the end of the conversation. Defaults to all runs.
            skip_role: Skip messages with this role.
            skip_status: Skip messages with this status.
            skip_history_messages: Skip messages that were tagged as history in previous runs.
        Returns:
            A list of Messages from the specified runs, excluding history messages.
        """
        if not self.runs:
            return []

        if skip_status is None:
            skip_status = [RunStatus.paused, RunStatus.cancelled, RunStatus.error]

        session_runs = self.runs
        # Filter by agent_id and team_id
        if agent_id:
            session_runs = [run for run in session_runs if hasattr(run, "agent_id") and run.agent_id == agent_id]  # type: ignore
        if team_id:
            session_runs = [run for run in session_runs if hasattr(run, "team_id") and run.team_id == team_id]  # type: ignore

        # Filter by status
        session_runs = [run for run in session_runs if hasattr(run, "status") and run.status not in skip_status]  # type: ignore

        # Filter by last_n
        runs_to_process = session_runs[-last_n:] if last_n is not None else session_runs
        messages_from_history = []
        system_message = None
        for run_response in runs_to_process:
            if not (run_response and run_response.messages):
                continue

            for message in run_response.messages:
                # Skip messages with specified role
                if skip_role and message.role == skip_role:
                    continue
                # Skip messages that were tagged as history in previous runs
                if hasattr(message, "from_history") and message.from_history and skip_history_messages:
                    continue
                if message.role == "system":
                    # Only add the system message once
                    if system_message is None:
                        system_message = message
                        messages_from_history.append(system_message)
                else:
                    messages_from_history.append(message)

        log_debug(f"Getting messages from previous runs: {len(messages_from_history)}")
        return messages_from_history

    def get_tool_calls(self, session_id: str, num_calls: Optional[int] = None) -> List[Dict[str, Any]]:
        """Returns a list of tool calls from the messages"""

        tool_calls = []
        session_runs = self.runs
        for run_response in session_runs[::-1]:
            if run_response and run_response.messages:
                for message in run_response.messages:
                    if message.tool_calls:
                        for tool_call in message.tool_calls:
                            tool_calls.append(tool_call)
                            if num_calls and len(tool_calls) >= num_calls:
                                return tool_calls
        return tool_calls

    def get_messages_for_session(
        self,
        user_role: str = "user",
        assistant_role: Optional[List[str]] = None,
        skip_history_messages: bool = True,
    ) -> List[Message]:
        """Returns a list of messages for the session that iterate through user message and assistant response."""

        if assistant_role is None:
            # TODO: Check if we still need CHATBOT as a role
            assistant_role = ["assistant", "model", "CHATBOT"]

        final_messages: List[Message] = []
        session_runs = self.runs
        for run_response in session_runs:
            if run_response and run_response.messages:
                user_message_from_run = None
                assistant_message_from_run = None

                # Start from the beginning to look for the user message
                for message in run_response.messages:
                    if hasattr(message, "from_history") and message.from_history and skip_history_messages:
                        continue
                    if message.role == user_role:
                        user_message_from_run = message
                        break

                # Start from the end to look for the assistant response
                for message in run_response.messages[::-1]:
                    if hasattr(message, "from_history") and message.from_history and skip_history_messages:
                        continue
                    if message.role in assistant_role:
                        assistant_message_from_run = message
                        break

                if user_message_from_run and assistant_message_from_run:
                    final_messages.append(user_message_from_run)
                    final_messages.append(assistant_message_from_run)
        return final_messages

    # Session Summary functions
    def get_response_format(self, model: "Model") -> Union[Dict[str, Any], Type[BaseModel]]:  # type: ignore
        if model.supports_native_structured_outputs:
            return SessionSummaryResponse

        elif model.supports_json_schema_outputs:
            return {
                "type": "json_schema",
                "json_schema": {
                    "name": SessionSummaryResponse.__name__,
                    "schema": SessionSummaryResponse.model_json_schema(),
                },
            }
        else:
            return {"type": "json_object"}

    def get_system_message(
        self,
        conversation: List[Message],
        response_format: Union[Dict[str, Any], Type[BaseModel]],
        session_summary_prompt: Optional[str] = None,
    ) -> Message:
        if session_summary_prompt is not None:
            return Message(role="system", content=session_summary_prompt)

        # -*- Return the default system message for session summary
        system_prompt = dedent("""\
        Analyze the following conversation between a user and an assistant, and extract the following details:
          - Summary (str): Provide a concise summary of the session, focusing on important information that would be helpful for future interactions.
          - Topics (Optional[List[str]]): List the topics discussed in the session.
        Keep the summary concise and to the point. Only include relevant information.

        <conversation>
        """)
        conversation_messages = []
        for message in conversation:
            if message.role == "user":
                conversation_messages.append(f"User: {message.content}")
            elif message.role in ["assistant", "model"]:
                conversation_messages.append(f"Assistant: {message.content}\n")
        system_prompt += "\n".join(conversation_messages)
        system_prompt += "</conversation>"

        if response_format == {"type": "json_object"}:
            from agno.utils.prompts import get_json_output_prompt

            system_prompt += "\n" + get_json_output_prompt(SessionSummaryResponse)  # type: ignore

        return Message(role="system", content=system_prompt)

    def _prepare_summary_messages(
        self,
        session_summary_model: "Model",  # type: ignore
        session_summary_prompt: Optional[str] = None,
    ) -> List[Message]:
        """Prepare messages for session summary generation"""
        response_format = self.get_response_format(session_summary_model)

        return [
            self.get_system_message(
                self.get_messages_for_session(),
                response_format=response_format,
                session_summary_prompt=session_summary_prompt,
            ),
            Message(role="user", content="Provide the summary of the conversation."),
        ]

    def _process_summary_response(self, summary_response, session_summary_model: "Model") -> Optional[SessionSummary]:  # type: ignore
        """Process the model response into a SessionSummary"""
        from datetime import datetime

        if summary_response is None:
            return None

        # Handle native structured outputs
        if (
            session_summary_model.supports_native_structured_outputs
            and summary_response.parsed is not None
            and isinstance(summary_response.parsed, SessionSummaryResponse)
        ):
            session_summary = SessionSummary(
                summary=summary_response.parsed.summary,
                topics=summary_response.parsed.topics,
                last_updated=datetime.now(),
            )
            self.summary = session_summary
            log_debug("Session summary created", center=True)
            return session_summary

        # Handle string responses
        if isinstance(summary_response.content, str):
            try:
                from agno.utils.string import parse_response_model_str

                parsed_summary = parse_response_model_str(summary_response.content, SessionSummaryResponse)

                if parsed_summary is not None:
                    session_summary = SessionSummary(
                        summary=parsed_summary.summary, topics=parsed_summary.topics, last_updated=datetime.now()
                    )
                    self.summary = session_summary
                    log_debug("Session summary created", center=True)
                    return session_summary
                else:
                    log_warning("Failed to parse session summary response")

            except Exception as e:
                log_warning(f"Failed to parse session summary response: {e}")

        return None

    def create_session_summary(
        self,
        session_summary_model: Optional["Model"] = None,  # type: ignore
        session_summary_prompt: Optional[str] = None,
    ) -> Optional[SessionSummary]:
        """Creates a summary of the session"""
        log_debug("Creating session summary", center=True)
        if session_summary_model is None:
            return None

        messages = self._prepare_summary_messages(session_summary_model, session_summary_prompt)
        response_format = self.get_response_format(session_summary_model)

        summary_response = session_summary_model.response(messages=messages, response_format=response_format)
        return self._process_summary_response(summary_response, session_summary_model)

    async def acreate_session_summary(
        self,
        session_summary_model: Optional["Model"] = None,  # type: ignore
        session_summary_prompt: Optional[str] = None,
    ) -> Optional[SessionSummary]:
        """Creates a summary of the session"""
        log_debug("Creating session summary", center=True)
        if session_summary_model is None:
            return None

        messages = self._prepare_summary_messages(session_summary_model, session_summary_prompt)
        response_format = self.get_response_format(session_summary_model)

        summary_response = await session_summary_model.aresponse(messages=messages, response_format=response_format)
        return self._process_summary_response(summary_response, session_summary_model)

    def get_session_summary(self) -> Optional[SessionSummary]:
        """Get the session summary for the session"""

        if self.summary is None:
            return None
        return self.summary

    # Chat History functions
    def get_chat_history(self) -> List[Message]:
        """Get the chat history for the session"""

        messages = []
        for run in self.runs:
            messages.extend([msg for msg in run.messages if not msg.from_history])
        self.chat_history = messages
        return messages
