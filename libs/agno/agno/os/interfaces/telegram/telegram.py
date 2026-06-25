import os

from typing import Dict, List, Literal, Optional, Union

from fastapi.routing import APIRouter

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.base import BaseInterface
from agno.os.interfaces.telegram.router import (
    DEFAULT_ERROR_MESSAGE,
    DEFAULT_HELP_MESSAGE,
    DEFAULT_NEW_MESSAGE,
    DEFAULT_START_MESSAGE,
    attach_routes,
)
from agno.team import RemoteTeam, Team
from agno.workflow import RemoteWorkflow, Workflow

DEFAULT_BOT_COMMANDS: List[Dict[str, str]] = [
    {"command": "start", "description": "Start the bot"},
    {"command": "help", "description": "Show help"},
    {"command": "new", "description": "Start a new conversation"},
]


class Telegram(BaseInterface):
    type = "telegram"

    router: APIRouter

    def __init__(
        self,
        agent: Optional[Union[Agent, RemoteAgent]] = None,
        team: Optional[Union[Team, RemoteTeam]] = None,
        workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
        prefix: str = "/telegram",
        tags: Optional[List[str]] = None,
        token: Optional[str] = None,
        reply_to_mentions_only: bool = True,
        reply_to_bot_messages: bool = True,
        start_message: str = DEFAULT_START_MESSAGE,
        help_message: str = DEFAULT_HELP_MESSAGE,
        error_message: str = DEFAULT_ERROR_MESSAGE,
        streaming: bool = True,
        show_reasoning: bool = False,
        commands: Optional[List[Dict[str, str]]] = None,
        register_commands: bool = True,
        new_message: str = DEFAULT_NEW_MESSAGE,
        quoted_responses: bool = False,
        mode: Literal["webhook", "polling"] = "webhook",
    ):
        self.agent = agent
        self.team = team
        self.workflow = workflow
        self.prefix = prefix
        self.tags = tags or ["Telegram"]
        self.token = token
        self.reply_to_mentions_only = reply_to_mentions_only
        self.reply_to_bot_messages = reply_to_bot_messages
        self.start_message = start_message
        self.help_message = help_message
        self.error_message = error_message
        self.streaming = streaming
        self.show_reasoning = show_reasoning
        self.commands = commands if commands is not None else DEFAULT_BOT_COMMANDS
        self.register_commands = register_commands
        self.new_message = new_message
        self.quoted_responses = quoted_responses
        self.mode = mode

        if not (self.agent or self.team or self.workflow):
            raise ValueError("Telegram requires an agent, team, or workflow")

        self._processor = None

    def _get_processor(self):
        """Lazy-initialize the message processor for polling mode."""
        if self._processor is None:
            from agno.os.interfaces.telegram.processor import TelegramMessageProcessor

            entity = self.agent or self.team or self.workflow
            assert entity is not None  # __init__ guarantees one of agent/team/workflow is set
            entity_type = "agent" if self.agent else "team" if self.team else "workflow"

            # Resolve token: explicit param → env var
            token = self.token or os.environ.get("TELEGRAM_TOKEN")
            if not token:
                raise ValueError("TELEGRAM_TOKEN is not set. Pass token='...' or set the TELEGRAM_TOKEN env var.")

            self._processor = TelegramMessageProcessor(  # type: ignore[assignment]
                entity=entity,
                entity_type=entity_type,
                token=token,
                reply_to_mentions_only=self.reply_to_mentions_only,
                reply_to_bot_messages=self.reply_to_bot_messages,
                start_message=self.start_message,
                help_message=self.help_message,
                error_message=self.error_message,
                streaming=self.streaming,
                show_reasoning=self.show_reasoning,
                commands=self.commands,
                register_commands=self.register_commands,
                new_message=self.new_message,
                quoted_responses=self.quoted_responses,
            )
        return self._processor

    def get_router(self) -> APIRouter:
        """Build and return a FastAPI APIRouter for webhook mode."""
        if self.mode == "polling":
            raise RuntimeError(
                "Telegram interface is configured for polling mode. Use start_polling() instead of mounting a router."
            )
        return attach_routes(
            router=APIRouter(prefix=self.prefix, tags=self.tags),  # type: ignore
            agent=self.agent,
            team=self.team,
            workflow=self.workflow,
            token=self.token,
            reply_to_mentions_only=self.reply_to_mentions_only,
            reply_to_bot_messages=self.reply_to_bot_messages,
            start_message=self.start_message,
            help_message=self.help_message,
            error_message=self.error_message,
            streaming=self.streaming,
            show_reasoning=self.show_reasoning,
            commands=self.commands,
            register_commands=self.register_commands,
            new_message=self.new_message,
            quoted_responses=self.quoted_responses,
        )

    async def start_polling(self) -> None:
        """Start long-polling mode (blocks until stopped).

        A polling-mode ``Telegram`` is a standalone runner — do not pass it to
        ``AgentOS`` (it contributes no routes and ``get_router()`` raises).

        Raises ``RuntimeError`` if mode is not ``"polling"``.
        """
        if self.mode != "polling":
            raise RuntimeError(
                "Telegram interface is configured for webhook mode. Set mode='polling' to use start_polling()."
            )

        from agno.os.interfaces.telegram.polling import TelegramPolling

        processor = self._get_processor()
        poller = TelegramPolling(processor)
        await poller.start()

    def run_polling(self) -> None:
        """Synchronous convenience wrapper around :meth:`start_polling`.

        Typical usage::

            tg = Telegram(team=team, mode="polling", token="...")
            tg.run_polling()
        """
        import asyncio

        try:
            asyncio.run(self.start_polling())
        except KeyboardInterrupt:
            # poller.start()'s finally already logs "stopped" and closes the session
            pass
