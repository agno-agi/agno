import json
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("slack_bolt", reason="slack_bolt not installed")

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from slack_bolt.async_app import AsyncApp

from agno.os.interfaces.slack import Slack
from agno.os.interfaces.slack.ids import ACTION_SUBMIT
from agno.os.interfaces.slack.router import attach_routes
from agno.run.base import RunStatus

from .conftest import (
    BOT_ID,
    BOT_USER_ID,
    SIGNING_SECRET,
    TOKEN,
    build_app,
    make_action_body,
    make_agent_mock,
    make_event_body,
    make_signed_request,
    make_stop_body,
    sign,
    wait_until,
)

pytestmark = pytest.mark.usefixtures("auth_test_mock")

_ROUTER = "agno.os.interfaces.slack.router"


@pytest.fixture
def handlers():
    """The handlers the listeners call, replaced so a route test sees only what Bolt hands off."""
    with (
        patch(f"{_ROUTER}.handle_message", new_callable=AsyncMock) as message,
        patch(f"{_ROUTER}.handle_app_home_opened", new_callable=AsyncMock) as home,
        patch(f"{_ROUTER}.handle_assistant_thread_started", new_callable=AsyncMock) as thread_started,
        patch(f"{_ROUTER}.handle_session_stopped", new_callable=AsyncMock) as stopped,
        patch(f"{_ROUTER}.hitl.handle_submit", new_callable=AsyncMock) as submit,
    ):
        yield {"message": message, "home": home, "thread_started": thread_started, "stopped": stopped, "submit": submit}


class TestSignatureAndBody:
    def test_unhandled_event_type_is_acked_without_bolt_warning(self, handlers, caplog):
        app = build_app(make_agent_mock())
        with TestClient(app) as client, caplog.at_level("WARNING"):
            response = make_signed_request(client, make_event_body(event_type="agent_session_title_changed"))
        assert response.status_code == 200
        assert not any("Unhandled request" in record.getMessage() for record in caplog.records)
        assert not handlers["message"].called

    def test_signed_event_is_acked_and_handed_to_handle_message(self, handlers):
        app = build_app(make_agent_mock())
        with TestClient(app) as client:
            response = make_signed_request(client, make_event_body())
            wait_until(lambda: handlers["message"].called)
        assert response.status_code == 200
        payload, slack_client, ctx = handlers["message"].call_args.args
        assert payload["event"]["text"] == "hello"
        assert slack_client.token == TOKEN
        assert ctx.app is app

    @pytest.mark.parametrize("signature", ["v0=bad", None])
    def test_bad_or_missing_signature_is_403(self, handlers, signature):
        body = json.dumps(make_event_body()).encode()
        headers = {"Content-Type": "application/json", "X-Slack-Request-Timestamp": str(int(time.time()))}
        if signature:
            headers["X-Slack-Signature"] = signature
        with TestClient(build_app(make_agent_mock())) as client:
            response = client.post("/events", content=body, headers=headers)
        assert response.status_code == 403
        assert not handlers["message"].called

    def test_unsigned_non_json_is_403_and_signed_non_json_is_acked(self, handlers):
        with TestClient(build_app(make_agent_mock())) as client:
            unsigned = client.post("/events", content=b"not json", headers={"Content-Type": "application/json"})
            signed = make_signed_request(client, b"not json")
            signed_array = make_signed_request(client, b"[1, 2]")
        assert unsigned.status_code == 403
        assert signed.status_code == 200
        assert signed_array.status_code == 200

    def test_handled_event_is_acked_with_json(self, handlers):
        with TestClient(build_app(make_agent_mock())) as client:
            response = make_signed_request(client, make_event_body())
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_url_verification_echoes_the_challenge(self):
        with TestClient(build_app(make_agent_mock())) as client:
            response = make_signed_request(client, {"type": "url_verification", "challenge": "abc123"})
        assert response.status_code == 200
        assert response.json()["challenge"] == "abc123"

    def test_ssl_check_is_acked(self):
        body = b"ssl_check=1&token=legacy"
        timestamp = str(int(time.time()))
        with TestClient(build_app(make_agent_mock())) as client:
            response = client.post(
                "/events",
                content=body,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-Slack-Request-Timestamp": timestamp,
                    "X-Slack-Signature": sign(body, timestamp),
                },
            )
        assert response.status_code == 200


class TestEventRetryDedupe:
    def test_duplicate_event_id_runs_once_and_unseen_retry_runs(self, handlers):
        with TestClient(build_app(make_agent_mock())) as client:
            make_signed_request(client, make_event_body(event_id="Ev1"))
            make_signed_request(client, make_event_body(event_id="Ev1"), headers={"X-Slack-Retry-Num": "1"})
            # The first delivery of Ev2 never reached us, so its retry runs
            make_signed_request(client, make_event_body(event_id="Ev2"), headers={"X-Slack-Retry-Num": "1"})
            wait_until(lambda: handlers["message"].call_count >= 2)
            time.sleep(0.1)
        assert [call.args[0]["event_id"] for call in handlers["message"].call_args_list] == ["Ev1", "Ev2"]

    def test_retry_without_event_id_is_dropped(self, handlers):
        body = make_event_body()
        body.pop("event_id")
        with TestClient(build_app(make_agent_mock())) as client:
            response = make_signed_request(client, body, headers={"X-Slack-Retry-Num": "1"})
            time.sleep(0.1)
        assert response.status_code == 200
        assert not handlers["message"].called

    @pytest.mark.parametrize("event_id", [None, "", 12345, {"nested": "object"}])
    def test_missing_or_malformed_event_id_does_not_crash(self, handlers, event_id):
        body = make_event_body(event_id=event_id)
        with TestClient(build_app(make_agent_mock())) as client:
            first = make_signed_request(client, body)
            retry = make_signed_request(client, body, headers={"X-Slack-Retry-Num": "1"})
            wait_until(lambda: handlers["message"].called)
            time.sleep(0.1)
        assert (first.status_code, retry.status_code) == (200, 200)
        # The first delivery is never lost because of a bad id; an id-less retry stays dropped
        assert handlers["message"].call_count == 1

    def test_bad_signature_never_marks_the_event_id_seen(self, handlers):
        with TestClient(build_app(make_agent_mock())) as client:
            forged = make_signed_request(client, make_event_body(event_id="Ev9"), "not-the-secret")
            genuine = make_signed_request(client, make_event_body(event_id="Ev9"))
            wait_until(lambda: handlers["message"].called)
        assert (forged.status_code, genuine.status_code) == (403, 200)
        assert handlers["message"].call_count == 1


class TestListeners:
    def test_each_event_reaches_its_listener(self, handlers):
        with TestClient(build_app(make_agent_mock())) as client:
            make_signed_request(client, make_event_body(event_type="app_mention", event_id="Ev1"))
            make_signed_request(
                client,
                {
                    "type": "event_callback",
                    "event_id": "Ev2",
                    "event": {"type": "app_home_opened", "user": "U123", "channel": "D1", "tab": "messages"},
                },
            )
            make_signed_request(
                client,
                {
                    "type": "event_callback",
                    "event_id": "Ev3",
                    "event": {"type": "assistant_thread_started", "assistant_thread": {"channel_id": "D1"}},
                },
            )
            make_signed_request(client, make_stop_body())
            wait_until(
                lambda: (
                    handlers["message"].called
                    and handlers["home"].called
                    and handlers["thread_started"].called
                    and handlers["stopped"].called
                )
            )
        assert handlers["message"].call_count == 1
        assert handlers["home"].call_count == 1
        assert handlers["thread_started"].call_count == 1
        assert handlers["stopped"].call_args.args[0]["event"]["type"] == "agent_session_stopped"

    def test_unknown_event_is_acked_without_a_handler(self, handlers):
        with TestClient(build_app(make_agent_mock())) as client:
            response = make_signed_request(
                client, {"type": "event_callback", "event_id": "Ev1", "event": {"type": "reaction_added", "user": "U1"}}
            )
            time.sleep(0.1)
        assert response.status_code == 200
        assert not any(handler.called for handler in handlers.values())

    def test_own_bot_message_is_dropped_by_bolt(self, handlers):
        with TestClient(build_app(make_agent_mock())) as client:
            response = make_signed_request(client, make_event_body(bot_id=BOT_ID, user=BOT_USER_ID))
            time.sleep(0.1)
        assert response.status_code == 200
        assert not handlers["message"].called

    def test_hitl_action_is_acked_and_handed_off(self, handlers):
        with TestClient(build_app(make_agent_mock())) as client:
            response = make_signed_request(client, make_action_body(ACTION_SUBMIT), path="/interactions")
            wait_until(lambda: handlers["submit"].called)
        assert response.status_code == 200
        assert handlers["submit"].call_args.args[0]["actions"][0]["action_id"] == ACTION_SUBMIT

    @pytest.mark.parametrize(
        "body",
        [
            make_action_body("some_other_app_button"),
            {"type": "view_closed", "user": {"id": "U1"}, "view": {"id": "V1", "type": "modal", "callback_id": "cb"}},
            {
                "type": "view_submission",
                "user": {"id": "U1"},
                "view": {"id": "V1", "type": "modal", "callback_id": "cb"},
            },
            {"type": "shortcut", "callback_id": "sc", "user": {"id": "U1"}, "team": {"id": "T1"}},
            {"type": "message_action", "callback_id": "ma", "user": {"id": "U1"}, "team": {"id": "T1"}},
            {
                "type": "block_suggestion",
                "action_id": "opt",
                "block_id": "b",
                "user": {"id": "U1"},
                "team": {"id": "T1"},
            },
        ],
    )
    def test_other_interactions_are_acked(self, handlers, body):
        with TestClient(build_app(make_agent_mock())) as client:
            response = make_signed_request(client, body, path="/interactions")
        assert response.status_code == 200
        assert not handlers["submit"].called

    def test_payload_no_listener_serves_is_acked(self):
        with TestClient(build_app(make_agent_mock())) as client:
            response = make_signed_request(
                client, {"type": "app_rate_limited", "team_id": "T1", "minute_rate_limited": 1, "api_app_id": "A1"}
            )
        assert response.status_code == 200


class TestAuthorize:
    def test_auth_test_runs_once_across_requests(self, handlers, auth_test_mock):
        with TestClient(build_app(make_agent_mock())) as client:
            for i in range(3):
                make_signed_request(client, make_event_body(event_id=f"Ev{i}", ts=f"1700000000.00010{i}"))
            wait_until(lambda: handlers["message"].call_count == 3)
        assert auth_test_mock.await_count == 1
        assert handlers["message"].call_args.args[2].bot_user_id == BOT_USER_ID

    def test_auth_test_failure_is_not_cached_and_logged_once_per_streak(self, handlers, auth_test_mock):
        auth_test_mock.side_effect = [TimeoutError(), Exception("down"), {"bot_id": BOT_ID, "user_id": BOT_USER_ID}]
        with (
            patch(f"{_ROUTER}.log_error") as log_error,
            TestClient(build_app(make_agent_mock())) as client,
        ):
            for i in range(4):
                make_signed_request(client, make_event_body(event_id=f"Ev{i}", ts=f"1700000000.00010{i}"))
            wait_until(lambda: handlers["message"].call_count == 4)
        assert handlers["message"].call_count == 4
        assert auth_test_mock.await_count == 3
        assert log_error.call_count == 1
        # A TimeoutError has no message, so the log names its type
        assert "TimeoutError" in log_error.call_args.args[0]

    def test_base_client_has_no_token(self):
        slack = Slack(agent=make_agent_mock(), token=TOKEN, signing_secret=SIGNING_SECRET)
        slack.get_router()
        assert isinstance(slack.ctx.bolt_app, AsyncApp)
        assert slack.ctx.bolt_app.client.token is None


class TestInstances:
    def test_import_without_slack_sdk_names_the_install(self):
        result = subprocess.run(
            [sys.executable, "-c", 'import sys; sys.modules["slack_sdk"] = None; import agno.os.interfaces.slack'],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0
        assert "pip install 'agno[slack]'" in result.stderr

    def test_operation_id_unique_across_instances(self):
        research = make_agent_mock()
        research.id, research.name = "research", "Research Agent"
        analyst = make_agent_mock()
        analyst.id, analyst.name = "analyst", "Analyst Agent"
        app = FastAPI()
        app.include_router(
            Slack(agent=research, prefix="/research", token=TOKEN, signing_secret=SIGNING_SECRET).get_router()
        )
        app.include_router(
            Slack(agent=analyst, prefix="/analyst", token=TOKEN, signing_secret=SIGNING_SECRET).get_router()
        )
        openapi = app.openapi()
        op_ids = [op.get("operationId") for path_ops in openapi["paths"].values() for op in path_ops.values()]
        assert len(op_ids) == 4
        assert len(op_ids) == len(set(op_ids))

    def test_two_instances_keep_their_own_secrets(self, handlers):
        app = FastAPI()
        first = APIRouter(prefix="/one")
        second = APIRouter(prefix="/two")
        attach_routes(first, agent=make_agent_mock(), token=TOKEN, signing_secret="secret-one")
        attach_routes(second, agent=make_agent_mock(), token=TOKEN, signing_secret="secret-two")
        app.include_router(first)
        app.include_router(second)
        with TestClient(app) as client:
            ok_one = make_signed_request(client, make_event_body(event_id="Ev1"), "secret-one", path="/one/events")
            ok_two = make_signed_request(client, make_event_body(event_id="Ev2"), "secret-two", path="/two/events")
            crossed = make_signed_request(client, make_event_body(event_id="Ev3"), "secret-one", path="/two/events")
        assert (ok_one.status_code, ok_two.status_code, crossed.status_code) == (200, 200, 403)

    def test_access_settings_set_after_construction_reach_the_handlers(self):
        slack = Slack(agent=make_agent_mock(), token=TOKEN, signing_secret=SIGNING_SECRET)
        runs = slack.ctx.runs
        # AgentOS checks slack.users at startup, so the handlers must see the same map
        slack.users = {"U123": "alice"}
        slack.approvers = ["U456"]
        slack.markdown = False
        slack.get_router()
        assert (slack.ctx.users, slack.ctx.approvers, slack.ctx.markdown) == ({"U123": "alice"}, ["U456"], False)
        assert slack.ctx.runs is runs
        # A new signing secret rebuilds Bolt and re-reads the bot ids; a new agent serves the next events
        bolt_app = slack.ctx.bolt_app
        slack.ctx.bot_id, slack.ctx.bot_user_id = "B123", "U999"
        slack.signing_secret = "rotated-secret"
        slack.agent = make_agent_mock()
        slack.get_router()
        assert slack.ctx.bolt_app is not bolt_app
        assert (slack.ctx.bot_id, slack.ctx.bot_user_id) == (None, None)
        assert slack.ctx.entity is slack.agent
        assert slack.ctx.runs is runs

    def test_get_router_twice_reuses_one_bolt_app(self, handlers):
        slack = Slack(agent=make_agent_mock(), token=TOKEN, signing_secret=SIGNING_SECRET)
        slack.get_router()
        bolt_app = slack.ctx.bolt_app
        app = FastAPI()
        app.include_router(slack.get_router())
        assert slack.ctx.bolt_app is bolt_app
        with TestClient(app) as client:
            make_signed_request(client, make_event_body(), path="/slack/events")
            wait_until(lambda: handlers["message"].called)
        # The run index the handler sees is the one Stop and HITL use
        assert handlers["message"].call_args.args[2].runs is slack.ctx.runs

    def test_env_oauth_settings_do_not_switch_bolt_to_oauth(self, handlers, monkeypatch):
        monkeypatch.setenv("SLACK_CLIENT_ID", "111.222")
        monkeypatch.setenv("SLACK_CLIENT_SECRET", "client-secret")
        slack = Slack(agent=make_agent_mock(), token=TOKEN, signing_secret=SIGNING_SECRET)
        router = slack.get_router()
        routes = {(route.path, method) for route in router.routes for method in route.methods}  # type: ignore[attr-defined]
        assert routes == {("/slack/events", "POST"), ("/slack/interactions", "POST")}
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as client:
            assert client.get("/slack/install").status_code in (404, 405)
            assert client.get("/slack/oauth_redirect").status_code in (404, 405)
            make_signed_request(client, make_event_body(), path="/slack/events")
            wait_until(lambda: handlers["message"].called)
        assert handlers["message"].call_args.args[1].token == TOKEN


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_astart_starts_task_delivery_and_aclose_stops_it_before_the_runs(self):
        slack = Slack(agent=make_agent_mock(), token=TOKEN, signing_secret=SIGNING_SECRET)
        # Without a Company nothing starts
        await slack.astart()
        calls = []
        delivery = AsyncMock()
        delivery.stop = AsyncMock(side_effect=lambda: calls.append("delivery"))
        slack.company = SimpleNamespace(deliver=True)
        with (
            patch("agno.os.interfaces.slack.company.TaskDelivery", return_value=delivery) as task_delivery,
            patch.object(slack.ctx.runs, "aclose", AsyncMock(side_effect=lambda: calls.append("runs"))),
        ):
            await slack.astart()
            await slack.aclose()
        task_delivery.assert_called_once_with(slack.ctx)
        delivery.start.assert_awaited_once()
        assert calls == ["delivery", "runs"]

    @pytest.mark.parametrize("through_slack", [True, False])
    def test_plain_fastapi_shutdown_closes_the_runs(self, through_slack):
        # Without AgentOS no interface lifespan runs, so the router's own shutdown handler closes the runs
        with patch("agno.os.interfaces.slack.runs.SlackRuns.aclose", new_callable=AsyncMock) as aclose:
            app = FastAPI()
            if through_slack:
                app.include_router(
                    Slack(agent=make_agent_mock(), token=TOKEN, signing_secret=SIGNING_SECRET).get_router()
                )
            else:
                router = APIRouter()
                attach_routes(router, agent=make_agent_mock(), token=TOKEN, signing_secret=SIGNING_SECRET)
                app.include_router(router)
            with TestClient(app):
                assert not aclose.called
        assert aclose.called

    @pytest.mark.asyncio
    @pytest.mark.parametrize("native", [True, False])
    async def test_aclose_freezes_cards_of_native_approvals_only(self, native):
        from slack_sdk.web.async_client import AsyncWebClient

        from .conftest import make_event_context

        agent = make_agent_mock()
        agent._uses_native_hitl = native
        slack = Slack(agent=agent, token=TOKEN, signing_secret=SIGNING_SECRET)
        event_context = make_event_context()
        slack.ctx.runs.register(event_context)
        slack.ctx.runs.park_paused(event_context, card_ts="card.1", awaiting_ts="await.1")
        with (
            patch.object(AsyncWebClient, "chat_update", new_callable=AsyncMock) as update,
            patch.object(AsyncWebClient, "chat_delete", new_callable=AsyncMock) as delete,
        ):
            await slack.aclose()
            # FastAPI's router shutdown and AgentOS's interface lifespan both close the interface
            await slack.aclose()
        if native:
            # A native approval waited in this process, so its card no longer offers live buttons
            update.assert_awaited_once()
            assert (update.call_args.kwargs["ts"], update.call_args.kwargs["text"]) == ("card.1", "Stopped")
            assert delete.call_args.kwargs["ts"] == "await.1"
        else:
            # An Agno agent's pause survives a restart and keeps its card
            assert not update.called and not delete.called

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [RunStatus.paused, RunStatus.completed])
    async def test_aclose_freezes_a_native_card_only_while_its_run_awaits_a_decision(self, status):
        from slack_sdk.web.async_client import AsyncWebClient

        from agno.run.agent import RunOutput

        from .conftest import make_event_context

        agent = make_agent_mock()
        agent._uses_native_hitl = True
        slack = Slack(agent=agent, token=TOKEN, signing_secret=SIGNING_SECRET)
        event_context = make_event_context()
        slack.ctx.runs.register(event_context)
        slack.ctx.runs.park_paused(event_context, card_ts="card.1", awaiting_ts="await.1")
        # A completed run was decided through the AgentOS continue route; its answer is already in the thread
        stored = RunOutput(run_id="run-1", status=status, metadata={"native_hitl": {"pending": ["nr-1"]}})
        with (
            patch("agno.os.interfaces.slack.executor.read_run", AsyncMock(return_value=stored)),
            patch.object(AsyncWebClient, "chat_update", new_callable=AsyncMock) as update,
            patch.object(AsyncWebClient, "chat_delete", new_callable=AsyncMock),
        ):
            await slack.aclose()
        assert update.called is (status == RunStatus.paused)
        assert slack.ctx.runs.parked() == []

    @pytest.mark.asyncio
    async def test_aclose_cancels_a_native_run_still_awaiting_a_decision(self, tmp_path):
        import asyncio
        from dataclasses import dataclass

        from slack_sdk.web.async_client import AsyncWebClient

        from agno.agents._hitl import current_bridge
        from agno.agents.base import BaseExternalAgent
        from agno.db.sqlite import SqliteDb
        from agno.run.agent import RunContentEvent

        from .conftest import make_event_context

        @dataclass
        class Harness(BaseExternalAgent):
            @property
            def _uses_native_hitl(self):
                return True

            async def _arun_adapter_stream(self, input, **kwargs):
                await current_bridge().request("Bash", {"command": "ls"}, {"sdk": "fixture"})
                yield RunContentEvent(content="done")

        agent = Harness(id="agent-1", db=SqliteDb(db_file=str(tmp_path / "native.db")), hitl_timeout=5)
        event_context = make_event_context()
        task = asyncio.create_task(
            agent.arun("work", session_id=event_context.session_id, run_id="run-1", user_id="U1")
        )
        try:
            for _ in range(300):
                stored = await agent.aget_run_output("run-1", session_id=event_context.session_id)
                if stored is not None and stored.status == RunStatus.paused:
                    break
                await asyncio.sleep(0.01)
            assert stored.status == RunStatus.paused
            slack = Slack(agent=agent, token=TOKEN, signing_secret=SIGNING_SECRET)
            slack.ctx.runs.register(event_context)
            slack.ctx.runs.park_paused(event_context, card_ts="card.1", awaiting_ts="await.1")
            with (
                patch.object(AsyncWebClient, "chat_update", new_callable=AsyncMock),
                patch.object(AsyncWebClient, "chat_delete", new_callable=AsyncMock),
            ):
                await slack.aclose()
            # The card reads Stopped, so a new message must not find the run still waiting for a decision
            stored = await agent.aget_run_output("run-1", session_id=event_context.session_id)
            assert stored.status == RunStatus.cancelled
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def test_slack_delivery_flags_reach_the_context(self):
        slack = Slack(
            agent=make_agent_mock(),
            token=TOKEN,
            signing_secret=SIGNING_SECRET,
            markdown=False,
            unfurl_links=False,
            unfurl_media=False,
        )
        assert (slack.ctx.markdown, slack.ctx.unfurl_links, slack.ctx.unfurl_media) == (False, False, False)
        default = Slack(agent=make_agent_mock(), token=TOKEN, signing_secret=SIGNING_SECRET)
        assert (default.ctx.markdown, default.ctx.unfurl_links, default.ctx.unfurl_media) == (True, True, True)
