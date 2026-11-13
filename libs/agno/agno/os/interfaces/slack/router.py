import re
from functools import partial
from ssl import SSLContext
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from agno.agent import Agent, RemoteAgent
from agno.agent.protocol import AgentProtocol

try:
    from slack_bolt.adapter.starlette.async_handler import AsyncSlackRequestHandler
    from slack_bolt.async_app import AsyncApp
    from slack_bolt.authorization import AuthorizeResult
    from slack_bolt.request.internals import parse_body
    from slack_bolt.response import BoltResponse
    from slack_sdk.signature import SignatureVerifier
    from slack_sdk.web.async_client import AsyncWebClient
except ImportError as e:
    raise ImportError("Slack dependencies not installed. Please install using `pip install 'agno[slack]'`") from e

from agno.os.interfaces.slack import hitl
from agno.os.interfaces.slack.context import SlackContext, build_context
from agno.os.interfaces.slack.executor import aclose_runs
from agno.os.interfaces.slack.handlers import (
    handle_app_home_opened,
    handle_assistant_thread_started,
    handle_message,
    handle_session_stopped,
)
from agno.os.interfaces.slack.ids import ACTION_CHECK_STATUS, ACTION_ROW_APPROVE, ACTION_ROW_REJECT, ACTION_SUBMIT
from agno.team import RemoteTeam, Team
from agno.utils.log import log_error, log_warning
from agno.workflow import RemoteWorkflow, Workflow

_Handler = Callable[[Dict[str, Any], Any, SlackContext], Awaitable[None]]


class SlackEventResponse(BaseModel):
    status: str = Field(default="ok")


class SlackChallengeResponse(BaseModel):
    challenge: str = Field(description="Challenge string to echo back to Slack")


_ACK = {"status": "ok"}


def _build_bolt_app(ctx: SlackContext) -> AsyncApp:
    """The Bolt app of one Slack interface: it verifies, authorizes, acks and hands each request to a handler."""

    async def _authorize(enterprise_id: Optional[str] = None, team_id: Optional[str] = None) -> AuthorizeResult:
        # Single workspace: the bot ids come from one auth.test, cached only once it succeeds
        if ctx.bot_user_id is None:
            try:
                auth = await ctx.web().auth_test()
            except Exception as e:
                # A failure must not drop the event: it runs without the ids, and the next request retries
                if "auth_test" not in ctx.failing:
                    log_error(f"Slack auth.test failed: {type(e).__name__}: {e}")
                ctx.failing.add("auth_test")
                return AuthorizeResult(enterprise_id=enterprise_id, team_id=team_id, bot_token=ctx.token)
            ctx.failing.discard("auth_test")
            ctx.bot_id = auth.get("bot_id")
            ctx.bot_user_id = auth.get("user_id")
        return AuthorizeResult(
            enterprise_id=enterprise_id,
            team_id=team_id,
            bot_token=ctx.token,
            bot_id=ctx.bot_id,
            bot_user_id=ctx.bot_user_id,
        )

    app = AsyncApp(
        signing_secret=ctx.signing_secret,
        # Explicit authorize: with SLACK_CLIENT_ID/SECRET in the env, Bolt would otherwise switch to OAuth
        authorize=_authorize,
        # Token-less: each listener gets a client with the token from _authorize
        client=AsyncWebClient(token=None, ssl=ctx.ssl),
        process_before_response=False,
        ignoring_self_events_enabled=True,
        raise_error_for_unhandled_request=False,
        attaching_conversation_kwargs_enabled=False,
    )

    async def _dedupe_events(body: Dict[str, Any], request: Any, next: Callable[[], Awaitable[Any]]) -> Any:
        # A retry is a duplicate only if the original delivery reached us, so dedupe on event_id
        # rather than dropping every retry. Without an event_id, drop the retry.
        event_id = body.get("event_id")
        if isinstance(event_id, str) and event_id:
            if ctx.dedupe.is_duplicate(event_id):
                return BoltResponse(status=200, body=_ACK)
        elif request.headers.get("x-slack-retry-num"):
            return BoltResponse(status=200, body=_ACK)
        return await next()

    app.use(_dedupe_events)

    def _listener(handler: _Handler) -> Callable[..., Awaitable[None]]:
        async def listener(ack: Any, body: Dict[str, Any], client: Any, context: Any) -> None:
            await ack()
            ctx.runs.spawn(handler(body, client, ctx.bind(context.get("app"))))

        return listener

    app.event("message")(_listener(handle_message))
    app.event("app_mention")(_listener(handle_message))
    app.event("app_home_opened")(_listener(handle_app_home_opened))
    app.event("assistant_thread_started")(_listener(handle_assistant_thread_started))
    app.event("agent_session_stopped")(_listener(handle_session_stopped))

    async def _ack_only(ack: Any) -> None:
        await ack()

    # Registered last so the listeners above win; any other subscribed event is acked without Bolt's unhandled warning
    app.event(re.compile(".*"))(_ack_only)

    app.action(ACTION_ROW_APPROVE)(_listener(hitl.handle_row_approve))
    app.action(ACTION_ROW_REJECT)(_listener(hitl.handle_row_reject))
    app.action(ACTION_CHECK_STATUS)(_listener(hitl.handle_check_status))
    app.action(ACTION_SUBMIT)(_listener(hitl.handle_submit))

    return app


def _dispatchable(parsed: Any) -> bool:
    if not isinstance(parsed, dict):
        return False
    # Bolt reads view["type"] unguarded for every view payload
    view = parsed.get("view")
    if isinstance(view, dict) and "type" not in view:
        return False
    return bool(parsed.get("type") or parsed.get("ssl_check"))


def attach_routes(
    router: APIRouter,
    agent: Optional[Union[Agent, RemoteAgent, AgentProtocol]] = None,
    team: Optional[Union[Team, RemoteTeam]] = None,
    workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
    reply_to_mentions_only: bool = True,
    token: Optional[str] = None,
    signing_secret: Optional[str] = None,
    streaming: bool = True,
    loading_messages: Optional[List[str]] = None,
    task_display_mode: str = "plan",
    loading_text: str = "Thinking...",
    suggested_prompts: Optional[List[Dict[str, str]]] = None,
    ssl: Optional[SSLContext] = None,
    buffer_size: int = 100,
    max_file_size: int = 1_073_741_824,  # 1GB
    resolve_user_identity: bool = False,
    respond_to_other_apps: bool = False,
    markdown: bool = True,
    unfurl_links: bool = True,
    unfurl_media: bool = True,
    approvers: Optional[List[str]] = None,
    users: Optional[Dict[str, str]] = None,
    context: Optional[SlackContext] = None,
) -> APIRouter:
    """
    Mount the Slack event and interaction routes on the router.

    The other arguments are the Slack(...) arguments of the same name; see Slack.__init__.

    Args:
        router: The router the Slack routes are added to
        agent: The agent to expose via Slack
        team: The team to expose via Slack
        workflow: The workflow to expose via Slack
        context: A SlackContext to reuse; built from the other arguments when None
    """
    # The context holds the runs, caches and Bolt app, so routes built again reuse them
    if context is None:
        context = build_context(
            agent=agent,
            team=team,
            workflow=workflow,
            token=token,
            signing_secret=signing_secret,
            reply_to_mentions_only=reply_to_mentions_only,
            streaming=streaming,
            loading_messages=loading_messages,
            task_display_mode=task_display_mode,
            loading_text=loading_text,
            suggested_prompts=suggested_prompts,
            ssl=ssl,
            buffer_size=buffer_size,
            max_file_size=max_file_size,
            resolve_user_identity=resolve_user_identity,
            respond_to_other_apps=respond_to_other_apps,
            markdown=markdown,
            unfurl_links=unfurl_links,
            unfurl_media=unfurl_media,
            approvers=approvers,
            users=users,
        )
        # Without AgentOS nothing else closes the runs
        router.add_event_handler("shutdown", partial(aclose_runs, context))
    if context.bolt_app is None:
        context.bolt_app = _build_bolt_app(context)
    handler = AsyncSlackRequestHandler(context.bolt_app)
    verifier = SignatureVerifier(context.signing_secret)
    # Multiple Slack instances can be mounted on one FastAPI app (e.g. /research
    # and /analyst). op_suffix makes each operation_id unique to avoid collisions.
    op_suffix = context.entity_name.lower().replace(" ", "_")

    async def _handle(request: Request) -> Response:
        # Slack retries any non-2xx, so a signed body Bolt cannot dispatch is acked and ignored
        body = await request.body()
        try:
            parsed = parse_body(body.decode("utf-8"), request.headers.get("content-type"))
        except Exception:
            parsed = None
        if not _dispatchable(parsed):
            try:
                valid = verifier.is_valid_request(body, dict(request.headers))
            except UnicodeDecodeError:
                valid = False
            if not valid:
                return JSONResponse(status_code=403, content={"detail": "Invalid signature"})
            log_warning("Ignoring Slack event with a non-JSON body")
            return JSONResponse(content=_ACK)
        # The FastAPI app reaches the handlers, for the platform authority of mapped users
        response = await handler.handle(request, addition_context_properties={"app": request.app})
        # Bolt answers a signed request no listener serves with 404; Slack would retry it or report failures
        if response.status_code == 404:
            return JSONResponse(content=_ACK)
        # Bolt answers a bad signature with 401; the interface answers 403 as the other webhook interfaces do
        if response.status_code == 401:
            return JSONResponse(status_code=403, content={"detail": "Invalid signature"})
        # Bolt acks a listener with an empty body; the routes declare the JSON ack
        if response.status_code == 200 and not response.body:
            return JSONResponse(content=_ACK)
        return response

    @router.post(
        "/events",
        operation_id=f"slack_events_{op_suffix}",
        name="slack_events",
        description="Process incoming Slack events",
        response_model=Union[SlackChallengeResponse, SlackEventResponse],
        response_model_exclude_none=True,
        responses={
            200: {"description": "Event processed successfully"},
            403: {"description": "Invalid Slack signature"},
        },
    )
    async def slack_events(request: Request):
        return await _handle(request)

    @router.post(
        "/interactions",
        operation_id=f"slack_interactions_{op_suffix}",
        name="slack_interactions",
        description="Handle Slack interactive components (HITL buttons / form submit)",
        response_model=SlackEventResponse,
        response_model_exclude_none=True,
        responses={
            200: {"description": "Interaction accepted"},
            403: {"description": "Invalid Slack signature"},
        },
    )
    async def slack_interactions(request: Request):
        return await _handle(request)

    return router
