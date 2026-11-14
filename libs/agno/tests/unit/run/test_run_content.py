"""The run content is derived from the messages a run produced."""

import json
from collections.abc import Iterator
from typing import Any

from agno.models.message import Message
from agno.run.agent import RunContentEvent
from agno.run.messages import RunMessages, get_run_content
from agno.tools.function import Function, ToolResult
from tests.unit.agent.test_run_content_last_model_call import ScriptedModel


def assistant(content: Any = None, tool_call: bool = False) -> Message:
    tool_calls = (
        [{"id": "call_1", "type": "function", "function": {"name": "f", "arguments": "{}"}}] if tool_call else None
    )
    return Message(role="assistant", content=content, tool_calls=tool_calls)


def tool_result(content: str, show_result: bool = False) -> Message:
    return Message(role="tool", content=content, tool_call_id="call_1", show_result=show_result)


def test_content_is_the_last_assistant_text():
    messages = [assistant("Let me check.", tool_call=True), tool_result("42"), assistant("The answer is 42.")]
    assert get_run_content(messages) == "The answer is 42."


def test_an_empty_final_call_falls_back_to_the_last_written_text():
    for empty in (None, "", "  \n"):
        messages = [assistant("I added it.", tool_call=True), tool_result("ok"), assistant(empty)]
        assert get_run_content(messages) == "I added it."


def test_shown_tool_results_are_kept_in_message_order():
    before = [assistant("Fetching.", tool_call=True), tool_result("TABLE", show_result=True), assistant("Here it is.")]
    assert get_run_content(before) == "TABLEHere it is."

    after = [assistant("Looking it up.", tool_call=True), tool_result("TOOL-OUT", show_result=True)]
    assert get_run_content(after) == "Looking it up.TOOL-OUT"


def test_shown_result_replaced_by_a_pointer_is_shown_in_full():
    offloaded = Message(role="tool", content="<result id=...>", tool_call_id="call_1", show_result=True)
    offloaded.shown_content = "FULL TABLE"
    assert get_run_content([assistant(tool_call=True), offloaded, assistant("Here it is.")]) == "FULL TABLEHere it is."
    assert Message.from_dict(offloaded.to_dict()).shown_content == "FULL TABLE"


def test_tool_results_that_are_not_shown_are_not_content():
    assert get_run_content([assistant(tool_call=True), tool_result("hidden")]) is None
    assert get_run_content([]) is None


def test_text_in_content_blocks_counts_as_text():
    assert get_run_content([assistant([{"type": "text", "text": "From a block."}])]) == "From a block."


def test_response_messages_exclude_the_run_input_and_history():
    system = Message(role="system", content="Be brief.")
    example = Message(role="assistant", content="A few-shot answer.")
    history = Message(role="assistant", content="An earlier answer.", from_history=True)
    user = Message(role="user", content="q")
    answer = assistant("The answer.")
    run_messages = RunMessages(
        messages=[system, example, history, user, answer],
        system_message=system,
        user_message=user,
        extra_messages=[example],
    )
    assert run_messages.get_response_messages() == [answer]
    assert run_messages.get_content() == "The answer."


def test_reasoning_added_before_the_model_call_is_not_the_content():
    user = Message(role="user", content="q")
    thinking = Message(role="assistant", content="<thinking>\nhmm\n</thinking>", reasoning_content="hmm")
    run_messages = RunMessages(messages=[user], user_message=user)
    run_messages.add_reasoning_message(thinking)
    assert run_messages.messages == [user, thinking]
    assert run_messages.get_content(default="from the model") == "from the model"

    run_messages.messages.append(assistant(tool_call=True))
    assert run_messages.get_content() is None


def test_input_assistant_messages_are_never_the_content():
    example = Message(role="assistant", content="A few-shot answer.")
    user = Message(role="user", content="q")
    run_messages = RunMessages(messages=[example, user], user_message=user, extra_messages=[example])
    # No model call added a message, so the caller's default stands
    assert run_messages.get_content(default="from the model") == "from the model"

    run_messages.messages.append(assistant(tool_call=True))
    run_messages.messages.append(tool_result("hidden"))
    assert run_messages.get_content(default="from the model") is None


def test_show_result_marker_survives_serialization():
    restored = Message.from_dict(tool_result("TABLE", show_result=True).to_dict())
    assert restored.show_result is True
    assert "show_result" not in tool_result("hidden").to_dict()


def add_to_cart(item: str) -> str:
    """Add an item to the grocery cart."""
    return f"added {item}"


NARRATED_SCRIPT = [
    {"content": "Let me check.", "tool": "add_to_cart", "args": '{"item": "apples"}'},
    {"content": "Final."},
]


def test_model_response_content_is_the_answer_of_the_tool_loop():
    model = ScriptedModel(NARRATED_SCRIPT)
    messages = [Message(role="user", content="q")]
    response = model.response(messages=messages, tools=[Function.from_callable(add_to_cart)])
    assert response.content == "Final."
    assert [m.role for m in messages] == ["user", "assistant", "tool", "assistant"]


def test_cache_hit_restores_the_messages_of_the_response(tmp_path):
    tools = [Function.from_callable(add_to_cart)]
    results = []
    for _ in ("miss", "hit"):
        model = ScriptedModel(NARRATED_SCRIPT)
        model.cache_response = True
        model.cache_dir = str(tmp_path)
        messages = [Message(role="user", content="q")]
        response = model.response(messages=messages, tools=tools)
        results.append((model.calls, response.content, [(m.role, m.content) for m in messages]))

    miss, hit = results
    assert (miss[0], hit[0]) == (2, 0)
    assert hit[1:] == miss[1:]


def test_cache_entry_without_messages_is_a_miss(tmp_path):
    model = ScriptedModel(NARRATED_SCRIPT)
    model.cache_dir = str(tmp_path)
    cache_file = model._get_model_cache_file_path("old-entry")
    cache_file.write_text(json.dumps({"timestamp": 0, "is_streaming": False, "result": {"content": "glued"}}))
    assert model._get_cached_model_response("old-entry") is None


def run_generator_tool(entrypoint: Any) -> str:
    model = ScriptedModel([{"tool": entrypoint.__name__, "args": "{}"}, {"content": "Done."}])
    messages = [Message(role="user", content="q")]
    model.response(messages=messages, tools=[Function.from_callable(entrypoint)])
    return [m.content for m in messages if m.role == "tool"][0]


def test_generator_tool_result_is_the_tool_result_it_yields():
    def research() -> Iterator[Any]:
        """Research a topic."""
        yield RunContentEvent(content="Thinking out loud. ")
        yield ToolResult(content="The finding.")

    assert run_generator_tool(research) == "The finding."


def test_generator_tool_without_a_tool_result_keeps_what_it_streamed():
    def research() -> Iterator[Any]:
        """Research a topic."""
        yield "Part one. "
        yield RunContentEvent(content="Part two.")

    assert run_generator_tool(research) == "Part one. Part two."
