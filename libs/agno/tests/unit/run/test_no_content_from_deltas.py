"""Guard: run content is derived from messages, never rebuilt by joining streamed content deltas.

Streamed content events are for display. Code that joins them back into a run's content disagrees
with the non-streaming path as soon as a model writes text before a tool call. This test lists
every place in the framework that accumulates ``.content`` with ``+=`` and fails when one is added
or removed, so a new accumulation is a decision and not an accident. To build content, use
``agno.run.messages.get_run_content`` or the run's final ``RunOutput``.
"""

import re
from collections import Counter
from pathlib import Path

import agno

AGNO_ROOT = Path(agno.__file__).parent

# Display code, provider adapters and integrations that never build a run's content
SKIPPED = ("utils/print_response/", "utils/pprint.py", "utils/models/", "tools/", "knowledge/", "vectordb/")
PROVIDER_ADAPTER = re.compile(r"^models/[a-z_0-9]+/")
ACCUMULATION = re.compile(r"\+= .*\.content\b")

ONE_MODEL_CALL = "deltas of one model call, the way its assistant message is built"
AUDIO = "audio bytes, not text content"
USER_GENERATOR_TOOL = "result of a generator tool that yields no ToolResult"
REASONING = "text of a reasoning model's single call"
PROMPT = "message text put into a prompt"
REMOTE_STREAM = "remote A2A agent: the stream is all the client receives"

ALLOWED = {
    "models/base.py": {
        "stream_data.response_content += model_response_delta.content": (1, ONE_MODEL_CALL),
        "stream_data.response_audio.content += audio_response.content  # type: ignore": (1, AUDIO),
        "function_call_output += item.content.model_dump_json()": (5, USER_GENERATOR_TOOL),
        'function_call_output += item.content or ""': (3, USER_GENERATOR_TOOL),
        "function_call_output += str(item.content)": (2, USER_GENERATOR_TOOL),
    },
    "agent/_response.py": {
        'model_response.audio.content += model_response_event.audio.content.encode("utf-8")': (1, AUDIO),
        "model_response.audio.content += model_response_event.audio.content": (1, AUDIO),
    },
    "team/_response.py": {
        'full_model_response.audio.content += model_response_event.audio.content.encode("utf-8")': (1, AUDIO),
        "full_model_response.audio.content += model_response_event.audio.content": (1, AUDIO),
        "run_response.content += model_response_event.content": (
            1,
            "member text shown while the team streams, replaced by the derived content when the model loop ends",
        ),
    },
    "agent/_session.py": {'gen_session_name_prompt += f"{message.role.upper()}: {message.content}\\n"': (1, PROMPT)},
    "team/_session.py": {'gen_session_name_prompt += f"{message.role.upper()}: {message.content}\\n"': (1, PROMPT)},
    "reasoning/azure_ai_foundry.py": {"reasoning_content += event.content": (2, REASONING)},
    "reasoning/openai.py": {"reasoning_content += event.content": (2, REASONING)},
    "reasoning/groq.py": {"reasoning_content += event.content": (2, REASONING)},
    "reasoning/ollama.py": {"reasoning_content += event.content": (2, REASONING)},
    "workflow/workflow.py": {
        "partial_step_content += event.content": (1, "partial step text kept when a workflow is cancelled"),
    },
    "client/a2a/utils.py": {"accumulated_content += event.content": (3, REMOTE_STREAM)},
    "agents/_response.py": {
        'self.content += event.content if isinstance(event.content, str) else ""': (1, "live terminal panel"),
    },
    "agents/base.py": {
        'accumulated_content += event.content or ""': (1, "external harness agents run their own loop"),
    },
}


def find_accumulations() -> dict:
    found: dict = {}
    for path in sorted(AGNO_ROOT.rglob("*.py")):
        relative = path.relative_to(AGNO_ROOT).as_posix()
        if relative.startswith(SKIPPED) or PROVIDER_ADAPTER.match(relative):
            continue
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if ACCUMULATION.search(line)]
        if lines:
            found[relative] = Counter(lines)
    return found


def test_content_is_not_accumulated_from_deltas_outside_the_known_places():
    found = find_accumulations()
    allowed = {path: Counter({line: count for line, (count, _) in lines.items()}) for path, lines in ALLOWED.items()}

    added = {path: dict(lines - allowed.get(path, Counter())) for path, lines in found.items()}
    added = {path: lines for path, lines in added.items() if lines}
    assert not added, (
        f"New code accumulates .content with +=: {added}. Derive run content from the run's messages "
        "(agno.run.messages.get_run_content) or use the final RunOutput instead of joining streamed deltas. "
        "If this is not run content, add it to ALLOWED with the reason."
    )

    removed = {path: dict(lines - found.get(path, Counter())) for path, lines in allowed.items()}
    removed = {path: lines for path, lines in removed.items() if lines}
    assert not removed, f"ALLOWED lists accumulations that no longer exist, remove them: {removed}"


def test_the_guard_sees_an_accumulation():
    assert ACCUMULATION.search("content += chunk.content")
    assert not ACCUMULATION.search("streamed_content.add(chunk)")
