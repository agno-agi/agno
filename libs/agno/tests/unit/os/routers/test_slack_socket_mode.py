import asyncio
import gc
import inspect
import os
import sys
import threading
import warnings
from contextlib import contextmanager
from dataclasses import fields
from unittest.mock import AsyncMock, Mock, patch

import pytest
from slack_sdk.errors import SlackApiError
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse

from agno.os.interfaces.slack import Slack
from agno.os.interfaces.slack.event_handler import SlackEventHandler
from agno.os.interfaces.slack.helpers import EventDeduplicator
from agno.os.interfaces.slack.hitl import HITLHandler
from agno.os.interfaces.slack.ids import ACTION_CHECK_STATUS, ACTION_ROW_APPROVE, ACTION_ROW_REJECT, ACTION_SUBMIT
from agno.os.interfaces.slack.router import build_handlers
from agno.os.interfaces.slack.socket_mode import SocketModeListener

from .conftest import make_agent_mock, make_async_client_mock, make_slack_mock, wait_for_call


@contextmanager
def _no_app_token_env():
    with patch.dict(os.environ):
        os.environ.pop("SLACK_APP_TOKEN", None)
        yield


def _slack(**kwargs) -> Slack:
    agent = make_agent_mock()
    agent.name = "Socket Agent"
    agent.id = "socket-agent"
    return Slack(agent=agent, **kwargs)


@contextmanager
def _handler_env(slack_mock=None):
    """Real handlers, mocked Slack clients. Stays active while dispatched tasks run."""
    with (
        patch(
            "agno.os.interfaces.slack.router.SlackTools", return_value=slack_mock or make_slack_mock(token="xoxb-test")
        ),
        patch("agno.os.interfaces.slack.event_handler.AsyncWebClient", return_value=make_async_client_mock()),
    ):
        yield


class TestEntryPoints:
    def test_socket_mode_entry_points_exist(self):
        assert inspect.iscoroutinefunction(Slack.astart_socket_mode)
        assert callable(Slack.start_socket_mode)
        assert not inspect.iscoroutinefunction(Slack.start_socket_mode)

    async def test_astart_without_any_app_token_raises_value_error(self):
        with _no_app_token_env():
            with pytest.raises(ValueError, match="SLACK_APP_TOKEN"):
                await _slack().astart_socket_mode()

    async def test_missing_app_token_is_rejected_before_anything_is_built(self):
        with _no_app_token_env(), patch("agno.os.interfaces.slack.router.SlackTools") as slack_tools:
            with pytest.raises(ValueError):
                await _slack().astart_socket_mode()
        slack_tools.assert_not_called()

    @pytest.mark.parametrize("argument, expected", [("xapp-arg", "xapp-arg"), (None, "xapp-env")])
    async def test_app_token_comes_from_the_argument_then_the_env(self, argument, expected):
        with (
            patch.dict("os.environ", {"SLACK_APP_TOKEN": "xapp-env"}),
            _handler_env(),
            patch("agno.os.interfaces.slack.socket_mode.run_socket_mode", new_callable=AsyncMock) as run,
        ):
            await _slack().astart_socket_mode(argument)
        assert run.await_args.args[0] == expected

    async def test_start_socket_mode_inside_running_loop_raises_naming_async_method(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with pytest.raises(RuntimeError, match="astart_socket_mode"):
                _slack().start_socket_mode("xapp-x")
            gc.collect()
        assert not [w for w in caught if "never awaited" in str(w.message)]

    def test_start_socket_mode_runs_the_async_method_outside_a_loop(self):
        with patch.object(Slack, "astart_socket_mode", new_callable=AsyncMock) as astart:
            _slack().start_socket_mode("xapp-x")
        astart.assert_awaited_once_with("xapp-x")

    async def test_astart_reports_missing_slack_extra_clearly(self):
        with patch.dict(sys.modules, {"agno.os.interfaces.slack.socket_mode": None}):
            with pytest.raises(ImportError, match=r"agno\[slack\]"):
                await _slack().astart_socket_mode("xapp-x")


class TestSharedHandlerConstruction:
    def test_build_handlers_returns_the_handler_objects_the_routes_use(self):
        agent = make_agent_mock()
        agent.name = "Router Agent"
        agent.id = "router-agent"
        with _handler_env():
            event_handler, hitl, event_dedupe = build_handlers(
                agent=agent, reply_to_mentions_only=False, markdown=False
            )

        assert isinstance(event_handler, SlackEventHandler)
        assert isinstance(hitl, HITLHandler)
        assert isinstance(event_dedupe, EventDeduplicator)
        assert event_handler.entity is agent and hitl.entity is agent
        assert event_handler.entity_id == "router-agent" and hitl.entity_id == "router-agent"
        assert event_handler.entity_type == "agent" and hitl.entity_type == "agent"
        assert event_handler.reply_to_mentions_only is False
        assert event_handler.markdown is False and hitl.markdown is False
        assert event_handler.slack_tools is hitl.slack_tools

    def test_build_handlers_records_own_bot_ids_from_auth_test(self):
        slack_mock = make_slack_mock(token="xoxb-test")
        slack_mock.client.auth_test = Mock(return_value={"bot_id": "B_OWN", "user_id": "U_OWN"})
        with _handler_env(slack_mock):
            event_handler, _, _ = build_handlers(agent=make_agent_mock())
        assert (event_handler.own_bot_id, event_handler.own_bot_user_id) == ("B_OWN", "U_OWN")

    def test_build_handlers_tolerates_auth_test_failure(self):
        slack_mock = make_slack_mock(token="xoxb-test")
        slack_mock.client.auth_test = Mock(side_effect=RuntimeError("no network"))
        with _handler_env(slack_mock):
            event_handler, _, _ = build_handlers(agent=make_agent_mock())
        assert (event_handler.own_bot_id, event_handler.own_bot_user_id) == (None, None)

    def test_build_handlers_enables_member_responses_on_a_team(self):
        team = Mock()
        team.name = "Ops Team"
        team.id = "ops-team"
        team.store_member_responses = False
        with _handler_env():
            event_handler, hitl, _ = build_handlers(team=team)
        assert team.store_member_responses is True
        assert event_handler.entity_type == "team" and hitl.entity is team

    def test_build_handlers_requires_an_entity(self):
        with _handler_env():
            with pytest.raises(ValueError, match="agent, team, or workflow"):
                build_handlers()

    async def test_astart_socket_mode_hands_shared_handlers_to_run_socket_mode(self):
        slack = _slack(streaming=False)
        with (
            _handler_env(),
            patch("agno.os.interfaces.slack.socket_mode.run_socket_mode", new_callable=AsyncMock) as run,
        ):
            await slack.astart_socket_mode("xapp-x")

        assert run.await_args.args == ("xapp-x",)
        kwargs = run.await_args.kwargs
        assert isinstance(kwargs["event_handler"], SlackEventHandler)
        assert isinstance(kwargs["hitl"], HITLHandler)
        assert isinstance(kwargs["event_dedupe"], EventDeduplicator)
        assert kwargs["event_handler"].entity is slack.agent
        assert kwargs["streaming"] is False
        assert kwargs["ssl"] is slack.ssl

    async def test_socket_mode_and_http_build_handlers_from_the_same_config(self):
        built = []

        def recording(**kwargs):
            handlers = build_handlers(**kwargs)
            built.append(handlers)
            return handlers

        slack = _slack(reply_to_mentions_only=False, loading_text="Working", markdown=False, buffer_size=7)
        with (
            _handler_env(),
            patch("agno.os.interfaces.slack.router.build_handlers", new=recording),
            patch("agno.os.interfaces.slack.slack.build_handlers", new=recording),
            patch("agno.os.interfaces.slack.socket_mode.run_socket_mode", new_callable=AsyncMock),
        ):
            slack.get_router()
            await slack.astart_socket_mode("xapp-x")

        assert len(built) == 2
        (http_events, http_hitl, _), (socket_events, socket_hitl, _) = built
        assert _config(http_events) == _config(socket_events)
        assert _config(http_hitl) == _config(socket_hitl)

    async def test_astart_builds_handlers_off_the_event_loop_thread(self):
        # build_handlers calls auth.test synchronously; on a live loop that must run in a worker thread.
        loop_thread = threading.get_ident()
        seen = {}

        def build_and_record_thread(**kwargs):
            seen["thread"] = threading.get_ident()
            return build_handlers(**kwargs)

        with (
            _handler_env(),
            patch("agno.os.interfaces.slack.slack.build_handlers", new=build_and_record_thread),
            patch("agno.os.interfaces.slack.socket_mode.run_socket_mode", new_callable=AsyncMock),
        ):
            await _slack().astart_socket_mode("xapp-x")

        assert seen["thread"] != loop_thread


def _config(handler) -> dict:
    # Instances built per call (client wrapper, name cache) differ by identity; everything else must match.
    return {
        f.name: getattr(handler, f.name) for f in fields(handler) if f.name not in ("slack_tools", "bot_name_resolver")
    }


# --- Socket Mode envelope dispatch -------------------------------------------------------------


def _envelope(payload, *, type="events_api", envelope_id="env-1", retry_attempt=None) -> SocketModeRequest:
    raw = {"type": type, "envelope_id": envelope_id, "payload": payload, "accepts_response_payload": False}
    if retry_attempt is not None:
        raw["retry_attempt"] = retry_attempt
        raw["retry_reason"] = "timeout"
    return SocketModeRequest.from_dict(raw)


def _event_body(event_id="Ev1", text="hello", event_type="message", **event_fields) -> dict:
    return {
        "type": "event_callback",
        "team_id": "T123",
        "event_id": event_id,
        "authorizations": [{"user_id": "U_BOT"}],
        "event": {
            "type": event_type,
            "channel_type": "im",
            "text": text,
            "user": "U456",
            "channel": "C123",
            "ts": "1708123456.000200",
            **event_fields,
        },
    }


def _handlers(agent=None, **kwargs):
    agent = agent or make_agent_mock()
    agent.id = "socket-agent"
    agent.name = "Socket Agent"
    return build_handlers(agent=agent, **kwargs)


def _listener(handlers, *, streaming=False):
    event_handler, hitl, event_dedupe = handlers
    return SocketModeListener(event_handler, hitl, event_dedupe, streaming=streaming)


async def _drain():
    # Let spawned handler tasks run to completion before asserting what did or did not happen.
    for _ in range(10):
        await asyncio.sleep(0)


class TestEventDispatch:
    async def test_events_api_envelope_is_acknowledged_before_processing(self):
        order = []
        with _handler_env():
            handlers = _handlers()
            handlers[0].handle_non_streaming = AsyncMock(side_effect=lambda data: order.append("handler"))
            client = AsyncMock()
            client.send_socket_mode_response = AsyncMock(side_effect=lambda resp: order.append("ack"))
            await _listener(handlers)(client, _envelope(_event_body()))
            await _drain()

        assert order == ["ack", "handler"]
        ack = client.send_socket_mode_response.await_args.args[0]
        assert isinstance(ack, SocketModeResponse) and ack.to_dict() == {"envelope_id": "env-1"}

    async def test_events_api_message_runs_through_the_shared_event_handler(self):
        agent = make_agent_mock()
        with _handler_env():
            handlers = _handlers(agent)
            await _listener(handlers)(AsyncMock(), _envelope(_event_body(text="over the socket")))
            await wait_for_call(agent.arun)

        agent.arun.assert_awaited_once()
        assert agent.arun.await_args.args[0] == "over the socket"
        assert agent.arun.await_args.kwargs["session_id"] == "socket-agent:C123:1708123456.000200"
        assert agent.arun.await_args.kwargs["user_id"] == "U456"

    @pytest.mark.parametrize(
        "streaming, called, idle",
        [(True, "handle_streaming", "handle_non_streaming"), (False, "handle_non_streaming", "handle_streaming")],
    )
    async def test_streaming_flag_selects_the_handler_method(self, streaming, called, idle):
        with _handler_env():
            handlers = _handlers()
            handlers[0].handle_streaming = AsyncMock()
            handlers[0].handle_non_streaming = AsyncMock()
            body = _event_body()
            await _listener(handlers, streaming=streaming)(AsyncMock(), _envelope(body))
            await _drain()

        getattr(handlers[0], called).assert_awaited_once_with(body)
        getattr(handlers[0], idle).assert_not_awaited()

    async def test_assistant_thread_started_reaches_handle_thread_started_when_streaming(self):
        with _handler_env():
            handlers = _handlers()
            handlers[0].handle_thread_started = AsyncMock()
            handlers[0].handle_streaming = AsyncMock()
            event = {"type": "assistant_thread_started", "assistant_thread": {"channel_id": "C1", "thread_ts": "t1"}}
            await _listener(handlers, streaming=True)(
                AsyncMock(), _envelope({"type": "event_callback", "event_id": "Ev9", "event": event})
            )
            await _drain()

        handlers[0].handle_thread_started.assert_awaited_once_with(event)
        handlers[0].handle_streaming.assert_not_awaited()

    async def test_assistant_thread_started_falls_through_to_the_message_path_when_not_streaming(self):
        # Mirrors the HTTP route: the prompts hook is streaming-only, otherwise the event takes the normal gate.
        with _handler_env():
            handlers = _handlers()
            handlers[0].handle_thread_started = AsyncMock()
            handlers[0].handle_non_streaming = AsyncMock()
            body = {
                "type": "event_callback",
                "event_id": "Ev9",
                "event": {"type": "assistant_thread_started", "assistant_thread": {}},
            }
            await _listener(handlers, streaming=False)(AsyncMock(), _envelope(body))
            await _drain()

        handlers[0].handle_thread_started.assert_not_awaited()
        handlers[0].handle_non_streaming.assert_awaited_once_with(body)

    async def test_should_process_is_consulted_with_the_inner_event(self):
        with _handler_env():
            handlers = _handlers()
            handlers[0].should_process = Mock(return_value=False)
            handlers[0].handle_non_streaming = AsyncMock()
            body = _event_body()
            await _listener(handlers)(AsyncMock(), _envelope(body))
            await _drain()

        handlers[0].should_process.assert_called_once_with(body["event"])
        handlers[0].handle_non_streaming.assert_not_awaited()

    async def test_own_bot_messages_are_filtered_by_the_existing_gate(self):
        agent = make_agent_mock()
        slack_mock = make_slack_mock(token="xoxb-test")
        slack_mock.client.auth_test = Mock(return_value={"bot_id": "B_OWN", "user_id": "U_OWN"})
        with _handler_env(slack_mock):
            handlers = _handlers(agent)
            await _listener(handlers)(AsyncMock(), _envelope(_event_body(bot_id="B_OWN")))
            await _drain()

        agent.arun.assert_not_awaited()

    async def test_payload_without_an_event_key_is_acknowledged_warned_and_ignored(self):
        # Slack's Socket Mode guide shows the bare event as the payload; its SDK shows the event_callback body.
        bare = {"type": "message", "channel_type": "im", "text": "hi", "user": "U456", "channel": "C123", "ts": "1.0"}
        client = AsyncMock()
        with _handler_env(), patch("agno.os.interfaces.slack.socket_mode.log_warning") as warn:
            handlers = _handlers()
            handlers[0].handle_non_streaming = AsyncMock()
            await _listener(handlers)(client, _envelope(bare))
            await _drain()

        client.send_socket_mode_response.assert_awaited_once()
        handlers[0].handle_non_streaming.assert_not_awaited()
        warn.assert_called_once()


# --- HITL interactions -------------------------------------------------------------------------


def _block_actions(action_id, payload_type="block_actions", actions=None) -> dict:
    if actions is None:
        actions = [{"action_id": action_id, "block_id": "row:r1:confirmation:pending", "value": "r1|run1|"}]
    return {
        "type": payload_type,
        "user": {"id": "U456"},
        "channel": {"id": "C123"},
        "message": {"ts": "1708123456.000300", "thread_ts": "1708123456.000200", "blocks": []},
        "actions": actions,
    }


_HITL_METHODS = ("handle_row_approve", "handle_row_reject", "handle_check_status", "handle_submit")


def _hitl_with_mocks(handlers):
    hitl = handlers[1]
    for name in _HITL_METHODS:
        setattr(hitl, name, AsyncMock())
    return hitl


class TestInteractiveDispatch:
    @pytest.mark.parametrize(
        "action_id, method",
        [
            (ACTION_ROW_APPROVE, "handle_row_approve"),
            (ACTION_ROW_REJECT, "handle_row_reject"),
            (ACTION_CHECK_STATUS, "handle_check_status"),
            (ACTION_SUBMIT, "handle_submit"),
        ],
    )
    async def test_block_action_routes_to_the_existing_hitl_method(self, action_id, method):
        client = AsyncMock()
        with _handler_env():
            handlers = _handlers()
            hitl = _hitl_with_mocks(handlers)
            payload = _block_actions(action_id)
            await _listener(handlers)(client, _envelope(payload, type="interactive", envelope_id="env-i"))
            await _drain()

        assert client.send_socket_mode_response.await_args.args[0].to_dict() == {"envelope_id": "env-i"}
        getattr(hitl, method).assert_awaited_once_with(payload)
        for other in _HITL_METHODS:
            if other != method:
                getattr(hitl, other).assert_not_awaited()

    @pytest.mark.parametrize(
        "payload",
        [
            _block_actions(ACTION_SUBMIT, actions=[]),
            _block_actions("some_other_app_button"),
            _block_actions(ACTION_SUBMIT, payload_type="view_submission"),
        ],
        ids=["missing-actions", "unknown-action-id", "not-block-actions"],
    )
    async def test_other_interactions_are_acknowledged_and_ignored(self, payload):
        client = AsyncMock()
        with _handler_env():
            handlers = _handlers()
            hitl = _hitl_with_mocks(handlers)
            await _listener(handlers)(client, _envelope(payload, type="interactive", envelope_id="env-i"))
            await _drain()

        client.send_socket_mode_response.assert_awaited_once()
        for name in _HITL_METHODS:
            getattr(hitl, name).assert_not_awaited()


# --- retries and failures ----------------------------------------------------------------------


class TestRetriesAndFailures:
    async def test_repeated_event_id_runs_once(self):
        agent = make_agent_mock()
        with _handler_env():
            listener = _listener(_handlers(agent))
            await listener(AsyncMock(), _envelope(_event_body("Ev2"), envelope_id="env-a"))
            await listener(AsyncMock(), _envelope(_event_body("Ev2"), envelope_id="env-b", retry_attempt=1))
            await wait_for_call(agent.arun)
            await _drain()

        agent.arun.assert_awaited_once()

    async def test_unseen_event_with_retry_attempt_is_processed_once(self):
        # The original delivery never reached us; Slack's retry is the only copy.
        agent = make_agent_mock()
        with _handler_env():
            listener = _listener(_handlers(agent))
            await listener(AsyncMock(), _envelope(_event_body("Ev3", text="only the retry"), retry_attempt=2))
            await wait_for_call(agent.arun)

        agent.arun.assert_awaited_once()
        assert agent.arun.await_args.args[0] == "only the retry"

    async def test_retry_without_usable_event_id_is_acknowledged_and_dropped(self):
        agent = make_agent_mock()
        client = AsyncMock()
        body = _event_body()
        del body["event_id"]
        with _handler_env():
            await _listener(_handlers(agent))(client, _envelope(body, retry_attempt=1))
            await _drain()

        client.send_socket_mode_response.assert_awaited_once()
        agent.arun.assert_not_awaited()

    async def test_the_shared_deduplicator_instance_is_the_one_consulted(self):
        with _handler_env():
            handlers = _handlers()
            handlers[2].is_duplicate = Mock(return_value=True)
            handlers[0].handle_non_streaming = AsyncMock()
            await _listener(handlers)(AsyncMock(), _envelope(_event_body("Ev4")))
            await _drain()

        handlers[2].is_duplicate.assert_called_once_with("Ev4")
        handlers[0].handle_non_streaming.assert_not_awaited()

    async def test_retried_interactive_envelope_is_acknowledged_and_dropped(self):
        client = AsyncMock()
        with _handler_env():
            handlers = _handlers()
            hitl = _hitl_with_mocks(handlers)
            await _listener(handlers)(
                client, _envelope(_block_actions(ACTION_SUBMIT), type="interactive", retry_attempt=1)
            )
            await _drain()

        client.send_socket_mode_response.assert_awaited_once()
        hitl.handle_submit.assert_not_awaited()

    async def test_acknowledgement_failure_dispatches_nothing_and_marks_nothing_seen(self):
        client = AsyncMock()
        client.send_socket_mode_response = AsyncMock(side_effect=ConnectionError("socket gone"))
        with _handler_env():
            handlers = _handlers()
            handlers[0].handle_non_streaming = AsyncMock()
            with pytest.raises(ConnectionError):
                await _listener(handlers)(client, _envelope(_event_body("Ev5")))
            await _drain()

        handlers[0].handle_non_streaming.assert_not_awaited()
        assert handlers[2].is_duplicate("Ev5") is False

    async def test_handler_exception_is_logged_and_the_listener_keeps_serving(self):
        with _handler_env(), patch("agno.os.interfaces.slack.socket_mode.log_error") as log_error:
            handlers = _handlers()
            handlers[0].handle_non_streaming = AsyncMock(side_effect=RuntimeError("boom in handler"))
            listener = _listener(handlers)
            await listener(AsyncMock(), _envelope(_event_body("Ev6")))
            await _drain()
            await listener(AsyncMock(), _envelope(_event_body("Ev7")))
            await _drain()

        assert handlers[0].handle_non_streaming.await_count == 2
        assert log_error.call_count == 2
        assert "boom in handler" in log_error.call_args.args[0]

    @pytest.mark.parametrize(
        "envelope_type, payload",
        [
            ("slash_commands", {"command": "/deploy", "text": "prod", "user_id": "U456", "channel_id": "C123"}),
            ("something_new", {"anything": True}),
        ],
        ids=["slash-command", "unknown-type"],
    )
    async def test_unsupported_envelope_types_are_acknowledged_and_ignored(self, envelope_type, payload):
        client = AsyncMock()
        with _handler_env():
            handlers = _handlers()
            handlers[0].handle_non_streaming = AsyncMock()
            hitl = _hitl_with_mocks(handlers)
            await _listener(handlers)(client, _envelope(payload, type=envelope_type, envelope_id="env-u"))
            await _drain()

        assert client.send_socket_mode_response.await_args.args[0].to_dict() == {"envelope_id": "env-u"}
        handlers[0].handle_non_streaming.assert_not_awaited()
        for name in _HITL_METHODS:
            getattr(hitl, name).assert_not_awaited()


# --- connection lifecycle ---------------------------------------------------------------------


def _fake_socket_client():
    client = AsyncMock()
    client.socket_mode_request_listeners = []
    client.wss_uri = None
    client.issue_new_wss_url = AsyncMock(return_value="wss://example.test/link")
    return client


@contextmanager
def _socket_env(client=None):
    client = client or _fake_socket_client()
    with (
        _handler_env(),
        patch("agno.os.interfaces.slack.socket_mode.SocketModeClient", return_value=client) as client_cls,
        patch("agno.os.interfaces.slack.socket_mode.AsyncWebClient") as web_client_cls,
    ):
        yield client, client_cls, web_client_cls


async def _start_until_connected(slack, client, token="xapp-x"):
    task = asyncio.create_task(slack.astart_socket_mode(token))
    await wait_for_call(client.connect)
    return task


async def _cancel(task):
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


class TestLifecycle:
    async def test_client_is_built_inside_the_loop_with_app_token_and_bot_web_client(self):
        loops = []
        with _socket_env() as (client, client_cls, web_client_cls):

            def build_client(**kwargs):
                loops.append(asyncio.get_running_loop())
                return client

            client_cls.side_effect = build_client
            slack = _slack()
            task = await _start_until_connected(slack, client, "xapp-token")
            await _cancel(task)

        client_cls.assert_called_once_with(app_token="xapp-token", web_client=web_client_cls.return_value)
        web_client_cls.assert_called_once_with(token="xoxb-test", ssl=slack.ssl)
        assert loops == [asyncio.get_running_loop()]

    async def test_wss_url_is_issued_before_connect(self):
        order = []
        client = _fake_socket_client()

        async def issue_url():
            order.append("issue")
            return "wss://example.test/link"

        client.issue_new_wss_url = issue_url
        client.connect = AsyncMock(side_effect=lambda: order.append("connect"))
        with _socket_env(client):
            task = await _start_until_connected(_slack(), client)
            await _cancel(task)

        assert order == ["issue", "connect"]
        assert client.wss_uri == "wss://example.test/link"

    async def test_invalid_app_token_is_a_startup_error_and_the_client_is_closed(self):
        client = _fake_socket_client()
        client.issue_new_wss_url = AsyncMock(
            side_effect=SlackApiError("The request to the Slack API failed.", {"ok": False, "error": "invalid_auth"})
        )
        with _socket_env(client):
            with pytest.raises(SlackApiError, match="invalid_auth"):
                await _slack().astart_socket_mode("xapp-bad")

        client.connect.assert_not_awaited()
        client.close.assert_awaited_once()

    async def test_connects_once_and_registers_exactly_one_listener(self):
        with _socket_env() as (client, _, _):
            task = await _start_until_connected(_slack(), client)
            await _drain()
            await _cancel(task)

        client.connect.assert_awaited_once()
        assert len(client.socket_mode_request_listeners) == 1
        assert isinstance(client.socket_mode_request_listeners[0], SocketModeListener)

    async def test_cancellation_closes_the_client_before_propagating(self):
        events = []
        client = _fake_socket_client()
        client.close = AsyncMock(side_effect=lambda: events.append("close"))
        with _socket_env(client):
            task = await _start_until_connected(_slack(), client)
            client.close.assert_not_awaited()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                events.append("cancelled")

        assert events == ["close", "cancelled"]

    async def test_background_tasks_are_tracked_until_they_finish(self):
        release = asyncio.Event()

        async def block_until_released(data):
            await release.wait()

        with _handler_env():
            handlers = _handlers()
            handlers[0].handle_non_streaming = AsyncMock(side_effect=block_until_released)
            listener = _listener(handlers)
            await listener(AsyncMock(), _envelope(_event_body("Ev8")))
            await _drain()
            assert len(listener.tasks) == 1 and not next(iter(listener.tasks)).done()
            release.set()
            await _drain()

        assert listener.tasks == set()

    async def test_task_exceptions_are_consumed_so_the_loop_never_reports_them(self):
        unraised = Mock()
        asyncio.get_running_loop().set_exception_handler(lambda loop, context: unraised(context))
        with _handler_env(), patch("agno.os.interfaces.slack.socket_mode.log_error"):
            handlers = _handlers()
            handlers[0].handle_non_streaming = AsyncMock(side_effect=RuntimeError("boom"))
            listener = _listener(handlers)
            await listener(AsyncMock(), _envelope(_event_body("Ev9")))
            await _drain()
            del listener, handlers
            gc.collect()

        unraised.assert_not_called()

    async def test_second_start_builds_a_fresh_client_and_listener(self):
        first, second = _fake_socket_client(), _fake_socket_client()
        with _socket_env(first) as (_, client_cls, _):
            client_cls.side_effect = [first, second]
            slack = _slack()
            await _cancel(await _start_until_connected(slack, first))
            await _cancel(await _start_until_connected(slack, second))

        assert client_cls.call_count == 2
        first_listener, second_listener = (
            first.socket_mode_request_listeners[0],
            second.socket_mode_request_listeners[0],
        )
        assert first_listener is not second_listener
        assert first_listener.tasks == set() and second_listener.tasks == set()
        assert first.close.await_count == 1 and second.close.await_count == 1
