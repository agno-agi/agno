"""Slack transport built on slack_bolt.

Bolt owns request verification, ``url_verification``, ``ssl_check``, own-bot event
filtering, and the acknowledge-then-continue dispatch model. This module builds the
``AsyncApp`` for one Slack app, registers the listeners that hand events to the Agno
handlers, and exposes a request handler that a FastAPI route can delegate to.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from fastapi import APIRouter, Request
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
from slack_bolt.async_app import AsyncApp
from slack_sdk.web.async_client import AsyncWebClient

from agno.os.interfaces.slack.config import SlackConfig
from agno.os.interfaces.slack.dedupe import EventDeduplicator, make_dedupe_middleware
from agno.os.interfaces.slack.event_handler import SlackEventHandler, make_web_client
from agno.os.interfaces.slack.helpers import BotNameResolver
from agno.os.interfaces.slack.hitl import HITLHandler
from agno.os.interfaces.slack.home import HomeTab
from agno.os.interfaces.slack.ids import (
    ACTION_CHECK_STATUS,
    ACTION_ROW_APPROVE,
    ACTION_ROW_REJECT,
    ACTION_SUBMIT,
)
from agno.team import RemoteTeam
from agno.utils.log import log_error

# Bolt injects these into listeners by argument name; a listener whose name Bolt
# does not know is called with nothing, so keep the listener signatures explicit.
AuthorizeFn = Callable[..., Awaitable[Any]]


@dataclass
class SlackRuntime:
    config: SlackConfig
    token: str
    dedupe: EventDeduplicator
    event_handler: SlackEventHandler
    hitl: HITLHandler
    home_tab: HomeTab


@dataclass
class SlackMount:
    config: SlackConfig
    runtime: SlackRuntime
    bolt_app: AsyncApp
    handler: AsyncSlackRequestHandler
    router: APIRouter


def build_runtime(config: SlackConfig) -> SlackRuntime:
    token = config.resolved_token()

    # Member HITL needs member runs embedded on the Team run (member_responses).
    # Without this, continue_run cannot reliably reload member tool state from DB.
    if config.team is not None and not isinstance(config.team, RemoteTeam):
        config.team.store_member_responses = True

    client = make_web_client(token, config.ssl)
    event_handler = SlackEventHandler(
        token=token,
        ssl=config.ssl,
        client=client,
        entity=config.entity,
        entity_id=config.entity_id,
        entity_name=config.entity_name,
        entity_type=config.entity_type,
        bot_name_resolver=BotNameResolver(),
        reply_to_mentions_only=config.reply_to_mentions_only,
        resolve_user_identity=config.resolve_user_identity,
        respond_to_other_apps=config.respond_to_other_apps,
        loading_text=config.loading_text,
        loading_messages=config.loading_messages,
        task_display_mode=config.task_display_mode,
        buffer_size=config.buffer_size,
        suggested_prompts=config.suggested_prompts,
        unfurl_links=config.unfurl_links,
        unfurl_media=config.unfurl_media,
        markdown=config.markdown,
        max_file_size=config.max_file_size,
        streaming=config.streaming,
        session_api=config.session_api,
        stop_message=config.stop_message,
        onboarding_message=config.onboarding_message,
        per_user_thread_sessions=config.per_user_thread_sessions,
        db=config.resolved_db(),
    )
    home_tab = HomeTab(event_handler._client, config.entity_name, config.entity_description)
    event_handler.home_tab_publisher = home_tab.publish
    hitl = HITLHandler(
        token=token,
        ssl=config.ssl,
        entity=config.entity,
        entity_id=config.entity_id,
        entity_name=config.entity_name,
        entity_type=config.entity_type,
        task_display_mode=config.task_display_mode,
        buffer_size=config.buffer_size,
        unfurl_links=config.unfurl_links,
        unfurl_media=config.unfurl_media,
        markdown=config.markdown,
        client=client,
        sessions=event_handler.sessions,
        active_runs=event_handler.active_runs,
        per_user_thread_sessions=config.per_user_thread_sessions,
    )
    return SlackRuntime(
        config=config,
        token=token,
        dedupe=EventDeduplicator(),
        event_handler=event_handler,
        hitl=hitl,
        home_tab=home_tab,
    )


def build_bolt_app(config: SlackConfig, runtime: SlackRuntime, *, authorize: Optional[AuthorizeFn] = None) -> AsyncApp:
    """Create the Bolt app for one Slack app.

    ``authorize`` replaces Bolt's ``auth.test`` lookup of the bot identity. Tests use it
    to avoid network calls; multi-workspace installs use it to resolve per-team tokens.
    Bolt refuses a fixed token together with ``authorize``, so the two are exclusive.
    """
    kwargs: dict = {
        "signing_secret": config.resolved_signing_secret(),
        "process_before_response": False,
        "request_verification_enabled": True,
        "ignoring_self_events_enabled": True,
        "url_verification_enabled": True,
        "ssl_check_enabled": True,
        "raise_error_for_unhandled_request": False,
    }
    if authorize is not None:
        kwargs["authorize"] = authorize
    else:
        kwargs["client"] = AsyncWebClient(token=runtime.token, ssl=config.ssl)

    app = AsyncApp(**kwargs)
    app.use(make_dedupe_middleware(runtime.dedupe))
    register_listeners(app, runtime)
    return app


def register_listeners(app: AsyncApp, runtime: SlackRuntime) -> None:
    events = runtime.event_handler
    hitl = runtime.hitl

    @app.event("assistant_thread_started")
    async def _on_thread_started(event: dict) -> None:
        await events.handle_thread_started(event)

    @app.event("app_mention")
    async def _on_app_mention(body: dict) -> None:
        await events.handle_message(body)

    @app.event("message")
    async def _on_message(body: dict) -> None:
        await events.handle_message(body)

    @app.event("app_home_opened")
    async def _on_home_opened(event: dict) -> None:
        await events.handle_home_opened(event)

    @app.event("agent_session_stopped")
    async def _on_session_stopped(event: dict) -> None:
        await events.handle_session_stopped(event)

    @app.event("agent_session_title_changed")
    async def _on_title_changed(event: dict) -> None:
        await events.handle_title_changed(event)

    @app.event("app_context_changed")
    async def _on_context_changed(event: dict) -> None:
        await events.handle_context_changed(event)

    @app.event("assistant_thread_context_changed")
    async def _on_assistant_context_changed(event: dict) -> None:
        await events.handle_context_changed(event)

    # Events without a handler still get a 200 so Slack does not retry them.
    @app.event(re.compile(".*"))
    async def _on_other_event() -> None:
        return None

    @app.action(ACTION_ROW_APPROVE)
    async def _on_row_approve(ack: Callable[..., Awaitable[Any]], body: dict) -> None:
        await ack()
        await hitl.handle_row_approve(body)

    @app.action(ACTION_ROW_REJECT)
    async def _on_row_reject(ack: Callable[..., Awaitable[Any]], body: dict) -> None:
        await ack()
        await hitl.handle_row_reject(body)

    @app.action(ACTION_CHECK_STATUS)
    async def _on_check_status(ack: Callable[..., Awaitable[Any]], body: dict) -> None:
        await ack()
        await hitl.handle_check_status(body)

    @app.action(ACTION_SUBMIT)
    async def _on_submit(ack: Callable[..., Awaitable[Any]], body: dict) -> None:
        await ack()
        await hitl.handle_submit(body)

    # Unknown action ids are acknowledged and ignored: another Slack app sharing the
    # endpoint, or a card from a newer build, must not produce an error for the user.
    @app.action(re.compile(".*"))
    async def _on_other_action(ack: Callable[..., Awaitable[Any]]) -> None:
        await ack()

    @app.error
    async def _on_error(error: Exception) -> None:
        log_error(f"Slack listener error: {error}")


def mount_slack(
    router: APIRouter,
    config: SlackConfig,
    *,
    authorize: Optional[AuthorizeFn] = None,
) -> SlackMount:
    """Build the runtime and Bolt app for ``config`` and attach the webhook routes."""
    runtime = build_runtime(config)
    bolt_app = build_bolt_app(config, runtime, authorize=authorize)
    handler = AsyncSlackRequestHandler(bolt_app)

    # Multiple Slack instances can be mounted on one FastAPI app (e.g. /research
    # and /analyst). The prefix makes each operation_id unique to avoid collisions.
    op_suffix = router.prefix.strip("/").replace("/", "_") or "slack"

    @router.post(
        "/events",
        operation_id=f"slack_events_{op_suffix}",
        name="slack_events",
        description="Process incoming Slack events",
        responses={
            200: {"description": "Event accepted"},
            401: {"description": "Invalid Slack signature"},
        },
    )
    async def slack_events(request: Request) -> Any:
        return await handler.handle(request)

    @router.post(
        "/interactions",
        operation_id=f"slack_interactions_{op_suffix}",
        name="slack_interactions",
        description="Handle Slack interactive components (HITL buttons / form submit)",
        responses={
            200: {"description": "Interaction accepted"},
            401: {"description": "Invalid Slack signature"},
        },
    )
    async def slack_interactions(request: Request) -> Any:
        return await handler.handle(request)

    return SlackMount(config=config, runtime=runtime, bolt_app=bolt_app, handler=handler, router=router)
