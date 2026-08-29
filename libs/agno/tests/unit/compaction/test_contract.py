"""Contract tests: inert off path, chaining strip, scrub interplay, resume selection."""

import sys
from typing import Any

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from test_cross_run_seam import EchoModel, make_agent, run_until_compacted  # noqa: E402

from agno.agent import Agent  # noqa: E402
from agno.compaction import Compaction  # noqa: E402
from agno.compaction.compaction import get_owner_records  # noqa: E402
from agno.compaction.prompts import SUMMARY_PREFIX  # noqa: E402
from agno.db.in_memory import InMemoryDb  # noqa: E402
from agno.models.response import ModelResponse  # noqa: E402


class TestOffPathGate:
    def test_no_compaction_code_reached_when_disabled(self, monkeypatch):
        # The seam gates on agent._compaction; a disabled agent must never construct views,
        # gauges, or records.
        import agno.compaction._view as view_module

        calls = []
        original = view_module.build_view

        def spy(*args: Any, **kwargs: Any):
            calls.append(1)
            return original(*args, **kwargs)

        monkeypatch.setattr(view_module, "build_view", spy)
        agent = Agent(
            id="plain",
            model=EchoModel("plain"),
            db=InMemoryDb(),
            add_history_to_context=True,
            telemetry=False,
        )
        output = agent.run("hello", session_id="s-gate")
        agent.run("again", session_id="s-gate")
        assert output.content == "plain"
        assert calls == []
        assert output.compaction_id is None
        session = agent.get_session(session_id="s-gate")
        assert not (session.session_data or {}).get("compaction")

    def test_off_path_message_assembly_unchanged(self):
        # Byte-identical assembly with and without the feature present in the build.
        def transcript(agent, session_id):
            outputs = []
            for text in ("first", "second", "third"):
                out = agent.run(text, session_id=session_id)
                outputs.append([(m.role, m.content) for m in out.messages or []])
            return outputs

        agent_a = Agent(
            id="gate-a", model=EchoModel("reply"), db=InMemoryDb(), add_history_to_context=True, telemetry=False
        )
        agent_b = Agent(
            id="gate-a",  # same id: assembly must not differ because the field exists
            model=EchoModel("reply"),
            db=InMemoryDb(),
            add_history_to_context=True,
            compaction=False,
            telemetry=False,
        )
        assert transcript(agent_a, "s1") == transcript(agent_b, "s1")


class TestChainingStrip:
    def test_provider_data_stripped_from_wire(self):
        class ChainingEchoModel(EchoModel):
            def invoke(self, *args: Any, messages=None, **kwargs: Any) -> ModelResponse:
                self.last_payload = list(messages or [])
                response = ModelResponse(role="assistant", content=self.reply)
                response.provider_data = {"response_id": f"resp_{len(self.last_payload)}"}
                return response

        model = ChainingEchoModel("word " * 200)
        agent = Agent(
            id="strip-agent",
            model=model,
            db=InMemoryDb(),
            add_history_to_context=True,
            compaction=Compaction(context_window=8_000, background=False),
            telemetry=False,
        )
        session_id = "s-strip"
        for _ in range(3):
            agent.run("go " + "word " * 50, session_id=session_id)
        # No assistant message on the wire carries provider_data while compaction is set —
        # server-side chaining would silently rebuild the full history behind the view.
        for message in model.last_payload:
            if message.role == "assistant":
                assert message.provider_data is None
        # The canonical transcript keeps it.
        session = agent.get_session(session_id=session_id)
        stored_assistants = [
            m for run in session.runs for m in (run.messages or []) if m.role == "assistant" and m.provider_data
        ]
        assert stored_assistants


class TestScrubInterplay:
    def test_summary_pair_never_persisted_by_default(self):
        agent = make_agent()
        session_id = "s-scrub-1"
        run_until_compacted(agent, session_id)
        agent.run("after " + "word " * 100, session_id=session_id)
        session = agent.get_session(session_id=session_id)
        for run in session.runs:
            for message in run.messages or []:
                content = message.content if isinstance(message.content, str) else ""
                assert not content.startswith(SUMMARY_PREFIX), "injected summary leaked into a stored run"

    def test_pair_persists_tagged_with_store_history_messages(self):
        agent = make_agent()
        agent.store_history_messages = True
        session_id = "s-scrub-2"
        run_until_compacted(agent, session_id)
        output = agent.run("after " + "word " * 100, session_id=session_id)
        session = agent.get_session(session_id=session_id)
        stored = next(run for run in session.runs if run.run_id == output.run_id)
        pair = [m for m in stored.messages or [] if isinstance(m.content, str) and m.content.startswith(SUMMARY_PREFIX)]
        assert pair and all(m.from_history for m in pair)
        # Re-reading does not double-inject: the next run still carries exactly one summary.
        next_output = agent.run("more " + "word " * 100, session_id=session_id)
        summaries = [
            m for m in next_output.messages or [] if isinstance(m.content, str) and m.content.startswith(SUMMARY_PREFIX)
        ]
        assert len(summaries) == 1


class TestResumeSelection:
    def test_fresh_run_after_fork_activity_unchanged(self):
        agent = make_agent()
        session_id = "s-resume-1"
        run_until_compacted(agent, session_id)
        session = agent.get_session(session_id=session_id)
        records = get_owner_records(session.session_data, "compaction-agent")
        newest = records[-1].id
        output = agent.run("fresh " + "word " * 100, session_id=session_id)
        assert output.compaction_id == newest
