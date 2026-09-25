"""Tests for the streamed tool call helpers in agno.utils.tools.

A fragment is attributed the way Agno's own tool call aggregators attribute
it, and these tests hold it to that by running one of those aggregators over
the same deltas. The OpenAI chat, watsonx, cerebras and litellm aggregators
are one rule written out four times: one entry per stream index, a missing
index read as zero, an entry's id taken from whichever of its deltas last
carried one, and each delta's argument text appended to the entry it landed
on. Agreeing with that is the property that matters, because that entry is
what the run makes the call with.
"""

import logging
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, NamedTuple, Optional, Tuple

from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall, ChoiceDeltaToolCallFunction
from pydantic import BaseModel

from agno.models.openai.chat import OpenAIChat
from agno.models.response import ToolExecution
from agno.utils import log as agno_log
from agno.utils.tools import (
    REFUSED_TOOL_CALL_ERROR,
    ToolCallArgsStream,
    TurnToolCalls,
    answer_streamed_tool_calls,
    extract_tool_call_arg_deltas,
    take_refused_tool_calls,
)


class _NamedTupleDelta(NamedTuple):
    """A tuple shaped delta, as SDKs that model deltas as records hand them over.

    It has no stream index, but being a tuple it does have a built-in `index`
    method, so a plain attribute read finds a callable instead of nothing.
    """

    id: Optional[str] = None
    function: Optional[Dict[str, Any]] = None


class _LoneDelta(BaseModel):
    """One delta reported on its own, not inside a list, as one provider does.

    That is how the Llama model class reports a streamed tool call: it assigns
    the provider's own delta object where a list of deltas belongs. Iterating
    a model like this one yields its (field, value) pairs rather than deltas,
    so the batch reads as calls naming nothing and carrying no argument text.
    """

    id: Optional[str] = None
    function: Optional[Dict[str, Any]] = None


def _drain(
    chunks: List[List[Any]],
    turn: Optional[TurnToolCalls] = None,
) -> Tuple[List[Tuple[str, Optional[str], str]], int, List[Tuple[Optional[str], Optional[str]]]]:
    """Feed a whole stream of deltas through the extractor, one chunk at a time.

    Returns the fragments to pass on, how many no call of the turn could be
    found for, and the calls whose arguments were not written as text.
    """
    if turn is None:
        turn = TurnToolCalls()
    deltas: List[Tuple[str, Optional[str], str]] = []
    unattributable = 0
    unwritten: List[Tuple[Optional[str], Optional[str]]] = []
    for chunk in chunks:
        chunk_deltas, chunk_unattributable, chunk_unwritten, _ = extract_tool_call_arg_deltas(chunk, turn)
        deltas.extend(chunk_deltas)
        unattributable += chunk_unattributable
        unwritten.extend(chunk_unwritten)
    return deltas, unattributable, unwritten


@contextmanager
def _warnings_logged() -> Iterator[List[logging.LogRecord]]:
    """Everything Agno logs at warning level, whichever logger carried it.

    ``log_warning`` writes to a process-global logger that a team run rebinds
    to the team logger and never rebinds back, so the same line is carried by
    one logger or another depending on what else ran earlier in the process.
    """
    records: List[logging.LogRecord] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Collector(logging.WARNING)
    loggers = list(
        {id(value): value for value in vars(agno_log).values() if isinstance(value, logging.Logger)}.values()
    )
    for agno_logger in loggers:
        agno_logger.addHandler(handler)
    try:
        yield records
    finally:
        for agno_logger in loggers:
            agno_logger.removeHandler(handler)


def _as_openai_deltas(chunks: List[List[Any]]) -> Iterator[ChoiceDeltaToolCall]:
    """The same deltas as the OpenAI SDK models them, for its own aggregator.

    Built without validation so that a delta can leave the index out, which is
    what an OpenAI compatible gateway sends and what `parse_tool_calls` reads
    as zero.
    """
    for chunk in chunks:
        for delta in chunk:
            function = delta.get("function") or {}
            yield ChoiceDeltaToolCall.model_construct(
                index=delta.get("index"),
                id=delta.get("id"),
                type="function",
                function=ChoiceDeltaToolCallFunction.model_construct(
                    name=function.get("name"), arguments=function.get("arguments")
                ),
            )


def _aggregated_by_agno(chunks: List[List[Any]]) -> Dict[Optional[str], str]:
    """What the run itself will call with, from Agno's own OpenAI aggregator."""
    return {
        call["id"]: call["function"]["arguments"]
        for call in OpenAIChat.parse_tool_calls(list(_as_openai_deltas(chunks)))
        if call
    }


def _streamed_by_call(deltas: List[Tuple[str, Optional[str], str]]) -> Dict[Optional[str], str]:
    """What a subscriber holds per call once it has appended every fragment."""
    assembled: Dict[Optional[str], str] = {}
    for tool_call_id, _tool_name, fragment in deltas:
        assembled[tool_call_id] = assembled.get(tool_call_id, "") + fragment
    return assembled


def test_indexed_provider_sends_id_and_name_once():
    """The ordinary case: one opening delta, then argument text on the same index."""
    deltas, unattributable, _ = _drain(
        [
            [{"index": 0, "id": "call_1", "function": {"name": "get_weather", "arguments": ""}}],
            [{"index": 0, "function": {"arguments": '{"city":'}}],
            [{"index": 0, "function": {"arguments": ' "Paris"}'}}],
        ]
    )

    assert deltas == [
        ("call_1", "get_weather", '{"city":'),
        ("call_1", "get_weather", ' "Paris"}'),
    ]
    assert unattributable == 0


def test_two_indexed_calls_stream_side_by_side():
    """Interleaved fragments follow the provider's own index."""
    deltas, unattributable, _ = _drain(
        [
            [
                {"index": 0, "id": "call_1", "function": {"name": "get_weather"}},
                {"index": 1, "id": "call_2", "function": {"name": "get_time"}},
            ],
            [
                {"index": 1, "function": {"arguments": '{"tz":'}},
                {"index": 0, "function": {"arguments": '{"city":'}},
            ],
            [{"index": 0, "function": {"arguments": ' "Paris"}'}}],
            [{"index": 1, "function": {"arguments": ' "UTC"}'}}],
        ]
    )

    assert deltas == [
        ("call_2", "get_time", '{"tz":'),
        ("call_1", "get_weather", '{"city":'),
        ("call_1", "get_weather", ' "Paris"}'),
        ("call_2", "get_time", ' "UTC"}'),
    ]
    assert unattributable == 0


def test_repeated_id_without_name_keeps_the_learned_name():
    """A provider that repeats the id on every fragment but the name only once."""
    deltas, _, _ = _drain(
        [
            [{"id": "call_1", "function": {"name": "get_weather"}}],
            [{"id": "call_1", "function": {"arguments": '{"city":'}}],
            [{"id": "call_1", "function": {"arguments": ' "Paris"}'}}],
        ]
    )

    assert deltas == [
        ("call_1", "get_weather", '{"city":'),
        ("call_1", "get_weather", ' "Paris"}'),
    ]


def test_name_arriving_after_the_id_attaches_to_the_call():
    """A provider that opens the call with an id and names it on a later fragment."""
    deltas, _, _ = _drain(
        [
            [{"index": 0, "id": "call_1"}],
            [{"index": 0, "function": {"name": "get_weather", "arguments": '{"city":'}}],
            [{"index": 0, "function": {"arguments": ' "Paris"}'}}],
        ]
    )

    assert deltas == [
        ("call_1", "get_weather", '{"city":'),
        ("call_1", "get_weather", ' "Paris"}'),
    ]


def test_tuple_shaped_delta_falls_back_instead_of_reading_its_index_method():
    """A tuple has an `index` method, which must not pass for a stream index."""
    deltas, _, _ = _drain(
        [
            [_NamedTupleDelta(id="call_1", function={"name": "get_weather"})],
            [_NamedTupleDelta(id="call_1", function={"arguments": '{"city": "Paris"}'})],
        ]
    )

    assert deltas == [("call_1", "get_weather", '{"city": "Paris"}')]


def test_a_call_id_the_provider_did_not_write_as_a_string_keeps_its_fragments():
    """An id of another type is the id the run calls under, so it is used as is.

    Nothing here narrows it: the finished call carries whatever the provider
    sent, and a subscriber has to be able to match its fragments to that.
    """
    deltas, unattributable, _ = _drain(
        [
            [{"index": 0, "id": 7, "function": {"name": "get_weather"}}],
            [{"index": 0, "function": {"arguments": '{"city": "Paris"}'}}],
        ]
    )

    assert deltas == [(7, "get_weather", '{"city": "Paris"}')]
    assert unattributable == 0


def test_a_call_id_the_provider_wrote_as_a_falsy_value_places_by_the_stream_index():
    """An id field filled in with a falsy placeholder says nothing about the call.

    A zero or an empty string there is not an id the finished call could be
    matched by, so it is read as no id at all and the provider's stream index
    places the fragment. A truthy id of another type is passed through
    unnarrowed instead, because the finished call carries it unnarrowed too.
    """
    for falsy_id in (0, ""):
        deltas, unattributable, _ = _drain(
            [
                [{"index": 0, "id": "call_1", "function": {"name": "get_weather"}}],
                [{"index": 0, "id": falsy_id, "function": {"arguments": '{"city": "Paris"}'}}],
            ]
        )

        assert deltas == [("call_1", "get_weather", '{"city": "Paris"}')], falsy_id
        assert unattributable == 0, falsy_id


def test_a_falsy_call_id_at_an_index_holding_no_call_places_nothing():
    """Read as no id, and its index names no call either, so nothing places it.

    The turn's one call sits at index one, so index zero is a slot no delta
    has named and there is no call of the turn to hand the fragment to.
    Passing the falsy id through instead would put a subscriber on argument
    text under an id no call was ever made under.
    """
    for falsy_id in (0, ""):
        deltas, unattributable, _ = _drain(
            [
                [{"index": 1, "id": "call_1", "function": {"name": "get_weather"}}],
                [{"index": 0, "id": falsy_id, "function": {"arguments": '{"city": "Paris"}'}}],
            ]
        )

        assert deltas == [], falsy_id
        assert unattributable == 1, falsy_id


def test_a_provider_that_numbers_no_delta_streams_the_whole_arguments():
    """The id rides the opening delta and nothing carries an index.

    Read strictly, the later fragments name no call and none of the arguments
    could be sent; read as Agno's own aggregators read them, they are the one
    call's and all of them go out.
    """
    chunks: List[List[Any]] = [
        [{"id": "call_1", "function": {"name": "get_weather", "arguments": ""}}],
        [{"function": {"arguments": '{"city":'}}],
        [{"function": {"arguments": ' "Paris"}'}}],
    ]
    deltas, unattributable, _ = _drain(chunks)

    assert _streamed_by_call(deltas) == {"call_1": '{"city": "Paris"}'}
    assert _streamed_by_call(deltas) == _aggregated_by_agno(chunks)
    assert unattributable == 0


def test_a_mixed_provider_streams_what_the_run_will_call_with():
    """One call carries an index, the other only an id, in the same turn.

    An index-less delta counts as index zero here as it does in the run
    itself, so the second call's id takes over that slot in both places and
    every fragment of the turn goes out under it. Streaming a reading of our
    own instead would leave a subscriber holding arguments no call was ever
    made with.
    """
    chunks: List[List[Any]] = [
        [
            {"index": 0, "id": "call_1", "function": {"name": "get_weather"}},
            {"id": "call_2", "function": {"name": "get_time"}},
        ],
        [{"index": 0, "function": {"arguments": '{"city":'}}],
        [{"id": "call_2", "function": {"arguments": '{"tz":'}}],
        [{"index": 0, "function": {"arguments": ' "Paris"}'}}],
        [{"id": "call_2", "function": {"arguments": ' "UTC"}'}}],
    ]
    deltas, unattributable, _ = _drain(chunks)

    assert _streamed_by_call(deltas) == {"call_2": '{"city":{"tz": "Paris"} "UTC"}'}
    assert _streamed_by_call(deltas) == _aggregated_by_agno(chunks)
    assert unattributable == 0


def test_two_index_less_calls_follow_the_id_each_delta_carries():
    """A provider that numbers nothing and opens a second call under a new id.

    Each fragment goes out under the id its own delta carried, which is the id
    that slot holds at the time. The run's aggregator ends by labelling the
    whole slot with the last id it saw, and no stream can go back and relabel
    text a subscriber already has, so the finished call is what says which
    arguments the call was made with.
    """
    chunks: List[List[Any]] = [
        [{"id": "call_1", "function": {"name": "get_weather", "arguments": '{"city":'}}],
        [{"id": "call_2", "function": {"name": "get_time", "arguments": '{"tz":'}}],
        [{"id": "call_1", "function": {"arguments": ' "Paris"}'}}],
        [{"id": "call_2", "function": {"arguments": ' "UTC"}'}}],
    ]
    deltas, _, _ = _drain(chunks)

    assert deltas == [
        ("call_1", "get_weather", '{"city":'),
        ("call_2", "get_time", '{"tz":'),
        ("call_1", "get_weather", ' "Paris"}'),
        ("call_2", "get_time", ' "UTC"}'),
    ]
    # Every fragment the run put in that one slot went out, in that order.
    assert "".join(fragment for _id, _name, fragment in deltas) == _aggregated_by_agno(chunks)["call_2"]


def test_a_fragment_that_arrives_before_any_call_is_named_is_counted_and_not_placed():
    """No id has been seen yet, so index zero resolves to no call at all.

    Agno gives a call the provider never named an id of its own only once the
    finished call is assembled, so there is nothing to send these under and
    the text is counted for the caller to report once for its stream.
    """
    deltas, unattributable, _ = _drain(
        [
            [{"function": {"name": "get_weather", "arguments": '{"city":'}}],
            [{"function": {"arguments": ' "Paris"}'}}],
        ]
    )

    assert deltas == []
    assert unattributable == 2


def test_a_fragment_that_names_nothing_joins_the_call_holding_index_zero():
    """One call is open, so index zero can only mean that one.

    Which is where the run itself puts such a fragment, so a subscriber ends
    on the arguments the call is made with.
    """
    chunks: List[List[Any]] = [
        [{"index": 0, "id": "call_1", "function": {"name": "get_weather", "arguments": '{"city":'}}],
        [{"function": {"arguments": "stray"}}],
        [{"index": 0, "function": {"arguments": ' "Paris"}'}}],
    ]
    deltas, unattributable, _ = _drain(chunks)

    assert _streamed_by_call(deltas) == {"call_1": '{"city":stray "Paris"}'}
    assert _streamed_by_call(deltas) == _aggregated_by_agno(chunks)
    assert unattributable == 0


def test_a_fragment_that_names_nothing_still_joins_index_zero_with_two_calls_open():
    """Two calls are open and a fragment names neither.

    Index zero hands the text to whichever of them holds that slot, and so
    does the run: reading it any other way would put a subscriber on arguments
    no call was made with, which is worse than agreeing with an ambiguous
    provider.
    """
    chunks: List[List[Any]] = [
        [
            {"index": 0, "id": "call_1", "function": {"name": "get_weather"}},
            {"index": 1, "id": "call_2", "function": {"name": "get_time"}},
        ],
        [{"function": {"arguments": '{"city": "Paris"}'}}],
    ]
    deltas, unattributable, _ = _drain(chunks)

    assert deltas == [("call_1", "get_weather", '{"city": "Paris"}')]
    assert _streamed_by_call(deltas)["call_1"] == _aggregated_by_agno(chunks)["call_1"]
    assert unattributable == 0


def test_an_unnumbered_fragment_beside_a_call_numbered_above_zero_is_counted():
    """The turn's one call sits at index one, and a fragment carries no index.

    Index zero is a slot no delta has named, and the run makes that slot a
    call of its own with no id and no name. There is nothing for a subscriber
    to hold such a fragment under, so it is counted rather than handed to the
    numbered call it does not belong to.
    """
    chunks: List[List[Any]] = [
        [{"index": 1, "id": "call_1", "function": {"name": "get_weather"}}],
        [{"function": {"arguments": '{"city": "Paris"}'}}],
    ]
    deltas, unattributable, _ = _drain(chunks)

    assert deltas == []
    assert unattributable == 1
    # The run puts that text on a call it gives no id, so no id could have
    # carried it to a subscriber.
    assert _aggregated_by_agno(chunks) == {None: '{"city": "Paris"}', "call_1": ""}


def test_a_numbered_fragment_follows_its_own_index_with_two_calls_open():
    """A provider that numbered the fragment has said which call it belongs to."""
    deltas, unattributable, _ = _drain(
        [
            [
                {"index": 0, "id": "call_1", "function": {"name": "get_weather"}},
                {"index": 1, "id": "call_2", "function": {"name": "get_time"}},
            ],
            [{"index": 1, "function": {"arguments": '{"tz": "UTC"}'}}],
        ]
    )

    assert deltas == [("call_2", "get_time", '{"tz": "UTC"}')]
    assert unattributable == 0


def test_arguments_the_provider_did_not_write_as_text_are_reported_with_their_call():
    """A delta whose arguments are a structure rather than the model's text.

    Mistral's streamed deltas type them either way, and the adapters that meet
    a mapping turn it into JSON text for the finished call. There is no
    fragment of the text the model wrote to send, and writing one here would
    put a subscriber on text of this library's making, so it is reported
    instead, under the call it happened to.
    """
    deltas, unattributable, unwritten = _drain(
        [[{"id": "call_1", "function": {"name": "get_weather", "arguments": {"city": "Paris"}}}]]
    )

    assert deltas == []
    assert unattributable == 0
    assert unwritten == [("call_1", "get_weather")]


def test_an_empty_structure_withholds_no_text_and_is_not_reported():
    """A call to a tool that takes no arguments, typed as a mapping.

    Nothing the model wrote is being kept from a subscriber here, so reporting
    it would be a false report of text withheld.
    """
    deltas, unattributable, unwritten = _drain(
        [
            [{"index": 0, "id": "call_1", "function": {"name": "get_time", "arguments": {}}}],
            [{"index": 1, "id": "call_2", "function": {"name": "get_date", "arguments": []}}],
        ]
    )

    assert deltas == []
    assert (unattributable, unwritten) == (0, [])


def test_a_delta_whose_arguments_are_not_text_still_names_its_call():
    """What such a delta does say about the call is still learned from it."""
    deltas, _, unwritten = _drain(
        [
            [{"index": 0, "id": "call_1", "function": {"name": "get_weather", "arguments": ["Paris"]}}],
            [{"index": 0, "function": {"arguments": '{"city": "Paris"}'}}],
        ]
    )

    assert deltas == [("call_1", "get_weather", '{"city": "Paris"}')]
    assert unwritten == [("call_1", "get_weather")]


def test_fragment_without_arguments_yields_nothing():
    turn = TurnToolCalls()

    assert extract_tool_call_arg_deltas([{"index": 0, "id": "call_1", "function": {"name": "f"}}], turn) == (
        [],
        0,
        [],
        None,
    )
    assert extract_tool_call_arg_deltas(None, turn) == ([], 0, [], None)
    assert extract_tool_call_arg_deltas([], turn) == ([], 0, [], None)


def test_a_batch_that_is_not_a_list_of_deltas_is_named_and_read_no_further():
    """A batch out of which no delta can be read is turned away by its shape.

    Iterating one yields whatever that object yields, and those contents name
    no call and carry no argument text, so nothing about them is reportable
    once they are in the loop. The turn learns nothing from such a batch, so a
    later fragment cannot resolve against a call it appeared to open.
    """
    turn = TurnToolCalls()
    lone = _LoneDelta(id="call_1", function={"name": "get_weather", "arguments": '{"city": "Paris"}'})

    assert extract_tool_call_arg_deltas(lone, turn) == ([], 0, [], "_LoneDelta")  # type: ignore[arg-type]
    assert (turn.id_by_index, turn.name_by_id) == ({}, {})
    # Any other shape a provider might report, rather than this one type.
    assert extract_tool_call_arg_deltas({"0": {"function": {"arguments": "{}"}}}, turn)[3] == "dict"  # type: ignore[arg-type]
    assert extract_tool_call_arg_deltas('{"city": "Paris"}', turn)[3] == "str"  # type: ignore[arg-type]


def test_a_restarted_stream_offers_its_retraced_fragments_again():
    """A provider stream that drops replays the turn from its opening delta.

    The retraced fragments go out again, because a subscriber can only append
    what it is sent and the run's own reassembly is retraced the same way.
    """
    chunks: List[List[Any]] = [
        [{"index": 0, "id": "call_1", "function": {"name": "get_weather", "arguments": ""}}],
        [{"index": 0, "function": {"arguments": '{"city":'}}],
        [{"index": 0, "id": "call_1", "function": {"name": "get_weather", "arguments": ""}}],
        [{"index": 0, "function": {"arguments": '{"city":'}}],
        [{"index": 0, "function": {"arguments": ' "Paris"}'}}],
    ]
    deltas, _, _ = _drain(chunks)

    # Retraced and all, which is what the run holds too.
    assert _streamed_by_call(deltas) == {"call_1": '{"city":{"city": "Paris"}'}
    assert _streamed_by_call(deltas) == _aggregated_by_agno(chunks)


def test_a_cleared_turn_resolves_no_index_of_the_turn_before_it():
    """Indexes restart at zero each turn, so a caller drops them between turns.

    Without that, the next turn's first fragment, which carries index zero and
    no id, would land on the finished call the last turn made under index zero.
    """
    turn = TurnToolCalls()
    _drain([[{"index": 0, "id": "call_1", "function": {"name": "get_weather", "arguments": '{"city":'}}]], turn)

    turn.clear()
    deltas, unattributable, _ = _drain([[{"index": 0, "function": {"arguments": ' "Paris"}'}}]], turn)

    assert deltas == []
    assert unattributable == 1


def test_a_delta_repeating_a_calls_id_and_name_is_neither_warned_about_nor_streamed():
    """Repeating a call's id and name on a later delta is a healthy stream.

    Some providers restate both on every delta of a call. The repetition adds
    no argument text, so there is nothing to pass on, and there is nothing
    wrong to report either.
    """
    stream = ToolCallArgsStream("session_1", "run_1")

    with _warnings_logged() as warnings:
        fragments = [
            triple
            for chunk in (
                [{"index": 0, "id": "call_1", "function": {"name": "get_weather", "arguments": '{"city":'}}],
                [{"index": 0, "id": "call_1", "function": {"name": "get_weather", "arguments": ""}}],
                [{"index": 0, "id": "call_1", "function": {"name": "get_weather", "arguments": ' "Paris"}'}}],
            )
            for triple in stream.fragments(chunk)
        ]

    assert _streamed_by_call(fragments) == {"call_1": '{"city": "Paris"}'}
    assert [record.getMessage() for record in warnings] == []


def test_tool_calls_reported_in_an_unreadable_shape_are_reported_once_and_not_streamed():
    """A provider that reports a streamed call as one delta object, not a list.

    No fragment of that call can be read, so an operator is told so instead of
    the loss passing in silence. The call is left off the stream's own record
    too, since a client shown no fragment of it has nothing left open.
    """
    lone = _LoneDelta(id="call_1", function={"name": "get_weather", "arguments": '{"city": "Paris"}'})
    stream = ToolCallArgsStream("session_1", "run_1")

    with _warnings_logged() as warnings:
        fragments = [triple for batch in (lone, lone) for triple in stream.fragments(batch)]  # type: ignore[arg-type]

    assert fragments == []
    assert stream.take_unanswered() == []
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "_LoneDelta" in message
    assert "no argument fragment is streamed" in message
    assert "session_id=session_1, run_id=run_1" in message


def test_a_fragment_arriving_after_the_run_took_a_call_up_reports_no_refusal():
    """A call the run has made is never reported to the client as never run.

    Providers sometimes trail a last argument fragment behind the call the run
    has already taken up, and some restate the id and name on every fragment.
    By then the client has watched that call start and finish, so returning it
    to the record of streamed calls the run has not answered could only ever
    close out a call the client saw succeed.
    """
    stream = ToolCallArgsStream("session_1", "run_1")

    streamed = list(
        stream.fragments([{"index": 0, "id": "call_1", "function": {"name": "set_flag", "arguments": '{"flag"'}}])
    )
    answer_streamed_tool_calls(stream, [ToolExecution(tool_call_id="call_1", tool_name="set_flag")])
    late = list(
        stream.fragments([{"index": 0, "id": "call_1", "function": {"name": "set_flag", "arguments": ": true}"}}])
    )

    assert streamed == [("call_1", "set_flag", '{"flag"')]
    assert late == [("call_1", "set_flag", ": true}")]
    assert take_refused_tool_calls(stream) == []


def test_a_reused_call_id_leaves_a_later_refused_call_open_on_the_client():
    """The cost of never returning an answered call to the record, on the record.

    A provider that reuses the id of a call the run has made for a genuinely
    new call, which the run then refuses, leaves that second call open on the
    client instead of closing it out. Nothing on a fragment marks where one
    call's arguments end and a reuse of its id begins, so this cannot be told
    apart from the trailing fragment of the first call, and a wrong report
    about a call the client watched succeed is the worse of the two harms.
    """
    stream = ToolCallArgsStream("session_1", "run_1")

    list(stream.fragments([{"index": 0, "id": "call_1", "function": {"name": "set_flag", "arguments": "{}"}}]))
    answer_streamed_tool_calls(stream, [ToolExecution(tool_call_id="call_1", tool_name="set_flag")])

    stream.begin_turn()
    reused = list(
        stream.fragments(
            [{"index": 0, "id": "call_1", "function": {"name": "set_flag", "arguments": '{"flag": true}'}}]
        )
    )

    assert reused == [("call_1", "set_flag", '{"flag": true}')]
    assert take_refused_tool_calls(stream) == []


def test_a_stream_drops_its_stream_indexes_at_a_turn_boundary():
    """A turn boundary ends the provider's numbering, not the record of calls.

    Indexes restart at zero each turn, so a fragment of the next turn that
    carries no id resolves against no call and is reported rather than placed
    on the call the last turn made under that index. The calls the run has not
    yet answered are a separate record and outlive the boundary.
    """
    stream = ToolCallArgsStream("session_1", "run_1")

    opening = list(
        stream.fragments([{"index": 0, "id": "call_1", "function": {"name": "get_weather", "arguments": '{"city":'}}])
    )
    stream.begin_turn()
    with _warnings_logged() as warnings:
        after_boundary = list(stream.fragments([{"index": 0, "function": {"arguments": ' "Paris"}'}}]))

    assert opening == [("call_1", "get_weather", '{"city":')]
    assert after_boundary == []
    assert len(warnings) == 1
    assert "carried neither a tool call id nor a provider stream index" in warnings[0].getMessage()
    assert stream.take_unanswered() == [("call_1", "get_weather")]


def test_a_call_the_run_takes_up_is_struck_off_and_the_rest_are_kept():
    """Taking one call up says nothing about the other calls of the same turn."""
    stream = ToolCallArgsStream("session_1", "run_1")

    list(
        stream.fragments(
            [
                {"index": 0, "id": "call_1", "function": {"name": "get_weather", "arguments": "{}"}},
                {"index": 1, "id": "call_2", "function": {"name": "set_flag", "arguments": "{}"}},
            ]
        )
    )
    stream.call_answered("call_1")

    assert stream.take_unanswered() == [("call_2", "set_flag")]


def test_the_unanswered_sweep_hands_each_call_over_once_and_once_only():
    """Whatever sweeps the record closes each call out exactly once.

    A run reaches the sweep more than once, at each turn boundary and again
    when it ends, so a call handed over is gone from the record and cannot be
    reported to the client a second time.
    """
    stream = ToolCallArgsStream("session_1", "run_1")

    list(
        stream.fragments(
            [
                {"index": 0, "id": "call_1", "function": {"name": "get_weather", "arguments": "{}"}},
                {"index": 1, "id": "call_2", "function": {"name": "set_flag", "arguments": "{}"}},
            ]
        )
    )

    assert stream.take_unanswered() == [("call_1", "get_weather"), ("call_2", "set_flag")]
    assert stream.take_unanswered() == []


def test_a_call_the_run_never_took_up_is_reported_to_the_client_as_refused():
    """The record exists to close out a streamed call the run declined to make."""
    stream = ToolCallArgsStream("session_1", "run_1")

    list(stream.fragments([{"index": 0, "id": "call_1", "function": {"name": "get_weather", "arguments": "{}"}}]))

    refused = take_refused_tool_calls(stream)

    assert [(tool.tool_call_id, tool.tool_name, tool.tool_call_error) for tool in refused] == [
        ("call_1", "get_weather", True)
    ]
    assert [tool.result for tool in refused] == [REFUSED_TOOL_CALL_ERROR]
