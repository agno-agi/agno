import asyncio
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, patch

import pytest
from slack_sdk.errors import SlackApiError

from agno.os.interfaces.slack import stream as stream_module
from agno.os.interfaces.slack.context import EventContext
from agno.os.interfaces.slack.state import StreamState
from agno.os.interfaces.slack.stream import _CONTINUED_PREFIX, _STREAM_CHAR_BUDGET, SlackStream, StreamStopped

from .conftest import SLACK_LIMIT, FakeSlack, make_ctx


def make_event_context() -> EventContext:
    return EventContext(
        run_id="run-1",
        session_id="s1",
        channel="C1",
        thread_ts="100.1",
        message_ts="100.1",
        owner="U1",
        user_id="U1",
        entity_id="agent-1",
        team_id="T1",
    )


def make_stream(client: Any, **ctx_overrides: Any) -> SlackStream:
    ctx = make_ctx(**ctx_overrides)
    event_context = make_event_context()
    ctx.runs.register(event_context)
    return SlackStream(client, event_context, ctx)


def card(card_id: str, status: str, title: str = "search") -> Dict[str, Any]:
    return {"type": "task_update", "id": card_id, "title": title, "status": status}


async def deliver(fake: FakeSlack, text: str, step: int = 97) -> SlackStream:
    stream = make_stream(fake)
    for i in range(0, len(text), step):
        await stream.append(markdown_text=text[i : i + step])
    await stream.stop()
    return stream


class TestCharBudget:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("unit", ["word ", "😀 ", "漢字テスト "])
    async def test_long_reply_split_across_messages_without_loss(self, unit):
        fake = FakeSlack()
        text = (unit * (14_000 // len(unit) + 1))[:14_000]
        await deliver(fake, text)
        assert fake.joined() == text
        assert len(fake.order) == 2
        assert all(m["stopped"] for m in fake.msgs.values())

    @pytest.mark.asyncio
    async def test_slack_counting_more_than_chars_still_loses_nothing(self):
        # Slack may count an emoji as two; its refusals rotate the reply instead of dropping text
        fake = FakeSlack(unit="utf16")
        text = "😀" * 9000
        stream = make_stream(fake)
        await stream.append(markdown_text=text)
        await stream.stop()
        assert fake.joined() == text
        assert all(m["size"] <= SLACK_LIMIT for m in fake.msgs.values())

    @pytest.mark.asyncio
    async def test_single_large_append_split_at_line_breaks(self):
        fake = FakeSlack()
        stream = make_stream(fake)
        text = "\n".join(f"line number {i:05d} with some words" for i in range(700))[:20_000]
        await stream.append(markdown_text=text)
        await stream.stop()
        texts = fake.texts()
        assert fake.joined() == text
        assert all(len(t) <= _STREAM_CHAR_BUDGET for t in texts)
        assert all(t[len(_CONTINUED_PREFIX) :].startswith("\n") for t in texts[1:])

    @pytest.mark.asyncio
    async def test_refused_text_is_never_sent_twice(self):
        fake = FakeSlack()
        stream = make_stream(fake)
        await stream.append(markdown_text="a" * 200)
        fake.fail_next = {"append": ["msg_too_long", "msg_too_long"]}
        piece = "".join(chr(ord("A") + i % 26) for i in range(400))
        await stream.append(markdown_text=piece)
        await stream.stop()
        assert fake.joined() == "a" * 200 + piece

    @pytest.mark.asyncio
    async def test_transient_failure_does_not_resend_or_miscount(self):
        fake = FakeSlack()
        stream = make_stream(fake)
        await stream.append(markdown_text="a" * 200)
        fake.fail_next = {"append": ["internal_error"]}
        with pytest.raises(SlackApiError):
            await stream.append(markdown_text="b" * 200)
        await stream.append(markdown_text="c" * 200)
        assert stream._chars == fake.msgs["900.1"]["size"]
        await stream.stop()
        assert fake.joined() == "a" * 200 + "c" * 200

    @pytest.mark.asyncio
    async def test_cut_never_splits_a_grapheme_cluster(self):
        fake = FakeSlack()
        stream = make_stream(fake)
        text = "👨‍👩‍👧 " * 3000
        await stream.append(markdown_text=text)
        await stream.stop()
        assert fake.joined() == text
        # Each cut falls on a space, so no message ends inside a cluster
        assert all(t[len(_CONTINUED_PREFIX) :].startswith(" ") for t in fake.texts()[1:])

    @pytest.mark.asyncio
    async def test_code_block_cut_by_the_budget_keeps_its_fence(self):
        fake = FakeSlack()
        code = "\n".join(f"# step {i}\nvalue = {i}" for i in range(800))
        text = f"Here is the script:\n```python\n{code}\n```\nDone."
        await deliver(fake, text)
        texts = fake.texts()
        assert len(texts) == 2
        assert texts[0].endswith("\n```")
        assert texts[1].startswith(_CONTINUED_PREFIX + "```\n")
        assert all(len(t) <= _STREAM_CHAR_BUDGET for t in texts)
        assert texts[0][: -len("\n```")] + texts[1][len(_CONTINUED_PREFIX + "```\n") :] == text

    @pytest.mark.asyncio
    async def test_text_without_fences_is_cut_unchanged(self):
        fake = FakeSlack()
        text = "\n".join(f"# step {i}\nvalue = {i}" for i in range(800))
        await deliver(fake, text)
        texts = fake.texts()
        assert len(texts) == 2
        assert not texts[0].endswith("```")
        assert texts[1].startswith(_CONTINUED_PREFIX + "\n")
        assert fake.joined() == text


class TestCards:
    @pytest.mark.asyncio
    async def test_card_limit_rotates_and_carries_open_cards(self):
        fake = FakeSlack()
        stream = make_stream(fake)
        await stream.append(chunks=[card("open", "in_progress", "long tool")])
        for i in range(60):
            await stream.append(chunks=[card(f"c{i}", "complete")])
        await stream.append(chunks=[card("open", "complete", "long tool")])
        await stream.stop()
        assert all(len(m["cards"]) <= 50 for m in fake.msgs.values())
        assert fake.msgs["900.1"]["cards"]["open"] == ("long tool: continued below", "complete")
        assert fake.msgs["900.1"]["status"] == "processing"
        assert fake.msgs["900.2"]["cards"]["open"] == ("long tool", "complete")

    @pytest.mark.asyncio
    async def test_card_updates_past_the_limit_do_not_rotate_again(self):
        fake = FakeSlack()
        stream = make_stream(fake)
        for i in range(46):
            await stream.append(chunks=[card(f"c{i}", "in_progress")])
        for i in range(46):
            await stream.append(chunks=[card(f"c{i}", "complete")])
        await stream.stop()
        assert len(fake.msgs) == 2
        assert all(status == "complete" for _, status in fake.msgs["900.2"]["cards"].values())

    @pytest.mark.asyncio
    async def test_parallel_cards_past_the_limit_rotate_once(self):
        fake = FakeSlack()
        stream = make_stream(fake)
        for i in range(52):
            await stream.append(chunks=[card(f"c{i}", "in_progress")])
        for i in range(52):
            await stream.append(chunks=[card(f"c{i}", "complete")])
        await stream.stop()
        assert len(fake.msgs) == 2

    @pytest.mark.asyncio
    async def test_card_closed_by_the_run_before_rotation_still_closes_in_the_old_message(self):
        fake = FakeSlack()
        state = StreamState()
        stream = make_stream(fake)
        state.track_task("tool", "search")
        await stream.append(chunks=[card("tool", "in_progress")])
        await stream.append(markdown_text="a" * 11_450)
        await stream.append(markdown_text="b" * 80)
        # The run marks the card complete before its update reaches the stream
        state.complete_task("tool")
        await stream.append(chunks=[card("tool", "complete")])
        await stream.stop()
        assert fake.msgs["900.1"]["cards"]["tool"][1] == "complete"
        assert fake.msgs["900.2"]["cards"]["tool"] == ("search", "complete")

    @pytest.mark.asyncio
    async def test_pause_stop_that_rotates_closes_the_old_cards(self):
        fake = FakeSlack()
        state = StreamState()
        stream = make_stream(fake)
        state.track_task("appr", "delete_file")
        await stream.append(chunks=[card("appr", "in_progress", "delete_file")])
        await stream.append(markdown_text="a" * 11_000)
        closing = state.resolve_all_pending("complete", suffix="paused")
        await stream.stop(markdown_text="b" * 1_000, chunks=closing, session_status="suspended")
        assert fake.msgs["900.1"]["cards"]["appr"][1] == "complete"
        assert fake.msgs["900.2"]["cards"]["appr"] == ("delete_file: paused", "complete")
        assert fake.msgs["900.2"]["status"] == "suspended"


class TestStopFallbacks:
    @pytest.mark.asyncio
    async def test_rotation_stop_refused_for_length_retries_bare(self):
        fake = FakeSlack()
        stream = make_stream(fake)
        await stream.append(chunks=[card("t1", "in_progress")])
        await stream.append(markdown_text="a" * 200)
        # Live Slack refused this stop with and without its status before a bare stop ended the message
        fake.fail_next = {"append": ["msg_too_long"], "stop": ["msg_too_long", "msg_too_long"]}
        await stream.append(markdown_text="b" * 200)
        await stream.stop()
        assert fake.joined() == "a" * 200 + "b" * 200
        assert fake.msgs["900.1"]["stopped"]
        bare = [c for c in fake.calls if c[0] == "stop"][2][1]
        assert bare["chunks"] is None and "session_status" not in bare

    @pytest.mark.asyncio
    async def test_rotation_stop_refused_status_retries_without_it(self):
        fake = FakeSlack()
        stream = make_stream(fake)
        await stream.append(markdown_text="a" * 200)
        fake.fail_next = {"append": ["msg_too_long"], "stop": ["invalid_arguments"]}
        await stream.append(markdown_text="b" * 200)
        await stream.stop()
        assert fake.msgs["900.1"]["stopped"]
        statuses = [c[1].get("session_status") for c in fake.calls if c[0] == "stop"]
        assert statuses[:2] == ["processing", None]

    @pytest.mark.asyncio
    async def test_final_stop_refused_for_length_retries_bare(self):
        fake = FakeSlack()
        stream = make_stream(fake)
        await stream.append(markdown_text="x" * 300)
        fake.fail_next = {"stop": ["msg_too_long"]}
        await stream.stop(chunks=[card("t9", "complete", "final")])
        assert fake.msgs["900.1"]["stopped"]
        assert stream.ended is True

    @pytest.mark.asyncio
    async def test_failed_flush_still_ends_the_message(self):
        fake = FakeSlack()
        stream = make_stream(fake)
        await stream.append(markdown_text="a" * 200)
        fake.fail_next = {"append": ["ratelimited"]}
        with pytest.raises(SlackApiError):
            await stream.stop(markdown_text="b" * 50)
        assert fake.msgs["900.1"]["stopped"]
        assert stream.closed


class TestTimer:
    @pytest.mark.asyncio
    async def test_timer_rotates_an_idle_stream_and_stop_cancels_it(self):
        fake = FakeSlack()
        with patch.object(stream_module, "_STREAM_ROTATE_SECONDS", 0.05):
            stream = make_stream(fake)
            await stream.append(chunks=[card("t1", "in_progress")])
            await asyncio.sleep(0.2)
            assert len(fake.order) >= 2
            assert fake.msgs["900.1"]["status"] == "processing"
            assert fake.msgs["900.1"]["cards"]["t1"] == ("search: continued below", "complete")
            reopened = [c[1]["chunks"] for c in fake.calls if c[0] == "start"][1]
            assert card("t1", "in_progress") in reopened
            await stream.stop()
            count = len(fake.order)
            await asyncio.sleep(0.15)
        assert len(fake.order) == count
        assert stream._timer is None

    @pytest.mark.asyncio
    async def test_no_timer_left_after_a_stop_that_rotates(self):
        fake = FakeSlack()
        stream = make_stream(fake)
        await stream.append(markdown_text="a" * 11_000)
        await stream.stop(markdown_text="b" * 1_000)
        assert len(fake.order) == 2
        assert stream._timer is None
        await asyncio.sleep(0)
        assert not [t for t in stream._ctx.runs._tasks if not t.done()]

    @pytest.mark.asyncio
    async def test_timer_racing_appends_loses_nothing(self):
        fake = FakeSlack(slow=0.03)
        with patch.object(stream_module, "_STREAM_ROTATE_SECONDS", 0.05):
            stream = make_stream(fake)
            for i in range(30):
                await stream.append(markdown_text=f"{i:03d}" * 40)
            await stream.stop()
            await asyncio.sleep(0.1)
        assert fake.joined() == "".join(f"{i:03d}" * 40 for i in range(30))
        assert all(m["stopped"] for m in fake.msgs.values())

    @pytest.mark.asyncio
    async def test_close_cancels_the_timer(self):
        fake = FakeSlack()
        stream = make_stream(fake)
        await stream.append(markdown_text="x" * 200)
        timer = stream._timer
        assert timer is not None
        stream.close()
        await asyncio.sleep(0)
        assert timer.cancelled()


class TestStopSignals:
    @pytest.mark.asyncio
    async def test_stopped_by_user_raises_and_stop_sends_nothing(self):
        fake = FakeSlack()
        stream = make_stream(fake)
        await stream.append(markdown_text="x" * 200)
        fake.fail_next = {"append": ["stopped_by_user"]}
        with pytest.raises(StreamStopped):
            await stream.append(markdown_text="y" * 200)
        await stream.stop()
        assert not [c for c in fake.calls if c[0] == "stop"]
        # No stopStream ran, so the caller ends the status
        assert stream.ended is False

    @pytest.mark.asyncio
    async def test_not_in_streaming_state_reopens_when_not_stopped(self):
        fake = FakeSlack()
        stream = make_stream(fake)
        await stream.append(markdown_text="a" * 200)
        fake.msgs["900.1"]["stopped"] = True
        await stream.append(markdown_text="b" * 200)
        await stream.stop()
        assert fake.joined() == "a" * 200 + "b" * 200

    @pytest.mark.asyncio
    async def test_not_in_streaming_state_is_a_stop_when_recorded(self):
        fake = FakeSlack()
        stream = make_stream(fake)
        await stream.append(markdown_text="x" * 200)
        stream._ctx.runs.record_stop("run-1")
        fake.msgs["900.1"]["stopped"] = True
        with pytest.raises(StreamStopped):
            await stream.append(markdown_text="y" * 200)

    @pytest.mark.asyncio
    async def test_ended_stream_takes_the_final_text(self):
        fake = FakeSlack()
        stream = make_stream(fake)
        await stream.append(markdown_text="a" * 200)
        fake.msgs["900.1"]["stopped"] = True
        await stream.stop(markdown_text="tail")
        assert fake.joined() == "a" * 200 + "tail"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("code", ["stopped_by_user", "message_not_in_streaming_state", "invalid_ts"])
    async def test_stop_tolerates_an_ended_stream(self, code):
        fake = FakeSlack()
        stream = make_stream(fake)
        await stream.append(markdown_text="x" * 200)
        fake.fail_next = {"stop": [code]}
        await stream.stop()
        assert stream.ended is False
        await stream.stop()
        assert len([c for c in fake.calls if c[0] == "stop"]) == 1

    @pytest.mark.asyncio
    async def test_stop_without_any_content_posts_nothing(self):
        fake = FakeSlack()
        stream = make_stream(fake)
        await stream.stop()
        assert fake.calls == []

    @pytest.mark.asyncio
    async def test_stream_messages_attach_to_the_event_context(self):
        fake = FakeSlack()
        stream = make_stream(fake)
        await stream.append(markdown_text="x" * 200)
        await stream.stop()
        assert stream._event_context.streaming_message_ts == ["900.1"]
        assert stream.ended is True

    @pytest.mark.asyncio
    async def test_recipient_defaults_to_the_sender(self):
        fake = FakeSlack()
        ctx = make_ctx()
        event_context = make_event_context()
        explicit: Optional[str] = "U_CLICKER"
        await SlackStream(fake, event_context, ctx).stop(markdown_text="x")
        await SlackStream(fake, event_context, ctx, recipient_user_id=explicit).stop(markdown_text="y")
        starts = [c[1] for c in fake.calls if c[0] == "start"]
        assert [s["recipient_user_id"] for s in starts] == ["U1", "U_CLICKER"]
        assert starts[0]["recipient_team_id"] == "T1"

    @pytest.mark.asyncio
    async def test_recipient_that_cannot_stream_gets_plain_messages(self):
        fake = FakeSlack()
        fake.fail_next = {"start": ["channel_type_not_supported"]}
        fake.chat_postMessage = AsyncMock()
        stream = make_stream(fake)
        text = "line\n" * 2_500
        await stream.append(chunks=[card("c1", "in_progress")])
        for i in range(0, len(text), 97):
            await stream.append(markdown_text=text[i : i + 97])
        await stream.stop(chunks=[card("c1", "complete")])
        posted = [c.kwargs for c in fake.chat_postMessage.call_args_list]
        # Past the char budget the text goes out as it fills, and the rest on stop, without loss
        assert len(posted) == 2
        assert "".join(p["text"] for p in posted) == text
        assert all((p["channel"], p["thread_ts"]) == ("C1", "100.1") for p in posted)
        # Only the refused startStream reached the stream methods; its cards are dropped
        assert [c[0] for c in fake.calls] == ["start"]
        assert stream.opened is True
        # No stopStream ended the status, so the caller clears it
        assert stream.ended is False
