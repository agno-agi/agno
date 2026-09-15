from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

from agno.models.response import ToolExecution
from agno.tools.function import Function, FunctionCall
from agno.utils.functions import get_function_call
from agno.utils.log import log_warning


def get_function_call_for_tool_call(
    tool_call: Dict[str, Any], functions: Optional[Dict[str, Function]] = None
) -> Optional[FunctionCall]:
    if tool_call.get("type") == "function":
        _tool_call_id = tool_call.get("id")
        _tool_call_function = tool_call.get("function")
        if _tool_call_function is not None:
            _tool_call_function_name = _tool_call_function.get("name")
            _tool_call_function_arguments_str = _tool_call_function.get("arguments") or "{}"
            if _tool_call_function_name is not None:
                return get_function_call(
                    name=_tool_call_function_name,
                    arguments=_tool_call_function_arguments_str,
                    call_id=_tool_call_id,
                    functions=functions,
                )
    return None


def extract_tool_call_from_string(text: str, start_tag: str = "<tool_call>", end_tag: str = "</tool_call>"):
    start_index = text.find(start_tag) + len(start_tag)
    end_index = text.find(end_tag)

    # Extracting the content between the tags
    return text[start_index:end_index].strip()


def remove_tool_calls_from_string(text: str, start_tag: str = "<tool_call>", end_tag: str = "</tool_call>"):
    """Remove multiple tool calls from a string."""
    while start_tag in text and end_tag in text:
        start_index = text.find(start_tag)
        end_index = text.find(end_tag) + len(end_tag)
        text = text[:start_index] + text[end_index:]
    return text


def extract_tool_from_xml(xml_str):
    # Find tool_name
    tool_name_start = xml_str.find("<tool_name>") + len("<tool_name>")
    tool_name_end = xml_str.find("</tool_name>")
    tool_name = xml_str[tool_name_start:tool_name_end].strip()

    # Find and process parameters block
    params_start = xml_str.find("<parameters>") + len("<parameters>")
    params_end = xml_str.find("</parameters>")
    parameters_block = xml_str[params_start:params_end].strip()

    # Extract individual parameters
    arguments = {}
    while parameters_block:
        # Find the next tag and its closing
        tag_start = parameters_block.find("<") + 1
        tag_end = parameters_block.find(">")
        tag_name = parameters_block[tag_start:tag_end]

        # Find the tag's closing counterpart
        value_start = tag_end + 1
        value_end = parameters_block.find(f"</{tag_name}>")
        value = parameters_block[value_start:value_end].strip()

        # Add to arguments
        arguments[tag_name] = value

        # Move past this tag
        parameters_block = parameters_block[value_end + len(f"</{tag_name}>") :].strip()

    return {"tool_name": tool_name, "parameters": arguments}


def remove_function_calls_from_string(
    text: str, start_tag: str = "<function_calls>", end_tag: str = "</function_calls>"
):
    """Remove multiple function calls from a string."""
    while start_tag in text and end_tag in text:
        start_index = text.find(start_tag)
        end_index = text.find(end_tag) + len(end_tag)
        text = text[:start_index] + text[end_index:]
    return text


def get_function_call_for_tool_execution(
    tool_execution: ToolExecution,
    functions: Optional[Dict[str, Function]] = None,
) -> Optional[FunctionCall]:
    import json

    _tool_call_id = tool_execution.tool_call_id
    _tool_call_function_name = tool_execution.tool_name or ""
    _tool_call_function_arguments_str = json.dumps(tool_execution.tool_args)
    return get_function_call(
        name=_tool_call_function_name,
        arguments=_tool_call_function_arguments_str,
        call_id=_tool_call_id,
        functions=functions,
    )


def _tool_call_delta_parts(tool_call: Any) -> Tuple[int, Optional[str], Optional[str], Any]:
    """Read (index, id, name, arguments) off one streamed tool call delta.

    Providers hand these to the run loop either as plain dicts or as their own
    SDK objects, so both shapes are read the same way. An index that is absent
    or is not an integer reads as zero, which is what every one of Agno's own
    aggregators makes of it: a delta modelled as a tuple, for instance, answers
    an `index` read with its own `index` method rather than with a stream index.

    The id and the arguments come back as the provider wrote them, whatever
    their type. The finished call carries that same unnarrowed id on its own
    ``Optional[str]`` field, so narrowing it here, and only here, would leave a
    subscriber holding fragments it cannot match to the call the run made.
    """
    if isinstance(tool_call, dict):
        function: Any = tool_call.get("function") or {}
        index = tool_call.get("index")
        tool_call_id = tool_call.get("id")
    else:
        function = getattr(tool_call, "function", None)
        index = getattr(tool_call, "index", None)
        tool_call_id = getattr(tool_call, "id", None)

    if isinstance(function, dict):
        name = function.get("name")
        arguments = function.get("arguments")
    else:
        name = getattr(function, "name", None)
        arguments = getattr(function, "arguments", None)

    return (
        index if isinstance(index, int) and not isinstance(index, bool) else 0,
        tool_call_id if tool_call_id else None,
        name if isinstance(name, str) and name else None,
        arguments,
    )


@dataclass
class TurnToolCalls:
    """What one model turn's tool call deltas have said about its calls so far.

    A provider puts a call's id and function name on one delta and ties the
    rest back to it, either by repeating the id or by its own stream index.
    An index is the provider's own numbering and restarts at zero every turn,
    so a caller drops the whole record at each turn boundary and no index can
    then resolve against a call an earlier turn made.
    """

    id_by_index: Dict[int, str] = field(default_factory=dict)
    name_by_id: Dict[str, str] = field(default_factory=dict)

    def clear(self) -> None:
        self.id_by_index.clear()
        self.name_by_id.clear()


def extract_tool_call_arg_deltas(
    tool_calls: Optional[List[Any]],
    turn: TurnToolCalls,
) -> Tuple[List[Tuple[str, Optional[str], str]], int, List[Tuple[Optional[str], Optional[str]]], Optional[str]]:
    """Pull the argument fragments out of one streamed tool call delta.

    A call's id and function name may arrive on its first delta only, and that
    delta often carries no arguments at all; later deltas carry an argument
    chunk plus something that ties them back to the call, either the id again
    or the provider's stream index. ``turn`` remembers both and is updated in
    place, so a fragment can be attributed without having seen the finished
    call. A turn can hold several calls, so their fragments interleave.

    Attribution is what Agno's own tool call aggregators do, exactly: one entry
    per stream index, a missing index read as zero, and an entry's id taken
    from whichever of its deltas last carried one. So where a provider is
    ambiguous the run and a subscriber read it the same way and cannot
    disagree, which is the property that matters: what a subscriber assembles
    is what the call is made with.

    Returns the (tool_call_id, tool_name, arguments_fragment) triples to pass
    on, one per fragment carrying argument text; how many fragments no call of
    the turn could be found for; the (id, name) of each fragment that carried
    arguments the provider wrote as a structure rather than as the text the
    model wrote, which has no fragment of that text to send and whose id is
    unknown when no call of the turn could be found for it either; and the type
    name of a whole batch that was not a list of deltas, out of which no delta
    can be read at all. Those three are the only text not passed on. Nothing
    else is held back, dropped or rewritten: a subscriber can only ever append
    what it is sent.
    """
    deltas: List[Tuple[str, Optional[str], str]] = []
    unattributable = 0
    unwritten: List[Tuple[Optional[str], Optional[str]]] = []
    # A provider that reports the turn's calls as one object rather than as a
    # list of them iterates into that object's own contents, which read as
    # deltas naming no call and carrying no argument text, so nothing about
    # them is reportable once they are in the loop. A batch is therefore turned
    # away by its own shape, and only a list is read delta by delta.
    if tool_calls is not None and not isinstance(tool_calls, list):
        return deltas, unattributable, unwritten, type(tool_calls).__name__
    for tool_call in tool_calls or []:
        index, tool_call_id, tool_name, arguments = _tool_call_delta_parts(tool_call)
        # An empty structure withholds no text the model wrote, so it is not
        # reported as though it had.
        structured_arguments = bool(arguments) and not isinstance(arguments, str)
        if not isinstance(arguments, str):
            arguments = None

        if tool_call_id is None:
            tool_call_id = turn.id_by_index.get(index)
        if tool_call_id is None:
            if structured_arguments:
                unwritten.append((None, tool_name))
            elif arguments:
                unattributable += 1
            continue

        turn.id_by_index[index] = tool_call_id
        # Learned whether or not this fragment carries arguments: what a call
        # is called outlives the fragment that named it.
        if tool_name is None:
            tool_name = turn.name_by_id.get(tool_call_id)
        else:
            turn.name_by_id[tool_call_id] = tool_name

        if structured_arguments:
            unwritten.append((tool_call_id, tool_name))
        elif arguments:
            deltas.append((tool_call_id, tool_name, arguments))
    return deltas, unattributable, unwritten, None


# Told to a client holding a call the run declined to make, for instance
# because the tool call limit was reached or no such tool exists.
REFUSED_TOOL_CALL_ERROR = "This tool call was not run."


class ToolCallArgsStream:
    """Turns a model stream's tool call deltas into argument fragments to send.

    Fragments are passed on exactly as the provider wrote them. Nothing is held
    back, dropped or rewritten, because a subscriber can only append what it is
    sent and so cannot be corrected afterwards. Three kinds of fragment cannot
    go out: one no call of the turn has been named for, one whose arguments the
    provider wrote as a structure rather than as text, and every fragment of a
    batch the provider did not report as a list of deltas, out of which no
    delta can be read at all. Each is reported rather than placed by a guess,
    once for the stream.

    An identity holds for one model turn: a provider's stream indexes restart
    at zero each turn, so the record is dropped at every turn boundary rather
    than letting a later fragment that carries no id resolve against a call the
    client has already seen finish.

    Fragments go out while the model is still writing the arguments, which is
    before the run can say whether the call will run at all. Every call the
    client has been shown is therefore remembered until the run takes it up, so
    a call the run refuses can be closed out rather than left open on the
    client for good. A call the run has taken up is never remembered again,
    which costs one thing knowingly: a provider that reuses that id for a
    second call the run then refuses leaves the second call open on the client,
    because nothing on a fragment marks where one call's arguments end and a
    reuse of its id begins. That is the lesser harm, a wrong report about a
    call the client watched succeed being the worse one.

    A run told not to stream events is sent no fragments and so is given no
    stream at all. A caller holds one exactly where the fragments it carries
    are the client's to receive, which is why a path can hand a stream to the
    chunk handler without also telling it to announce anything else.
    """

    def __init__(self, session_id: Optional[str], run_id: Optional[str]) -> None:
        self._turn = TurnToolCalls()
        # tool_call_id -> tool name, for streamed calls the run has neither
        # started, paused, nor finished
        self._unanswered: Dict[str, Optional[str]] = {}
        # The calls of this stream the run has taken up
        self._answered: Set[str] = set()
        self._run_label = f"(session_id={session_id}, run_id={run_id})"
        self._reported_unattributable = False
        self._reported_unwritten = False
        self._reported_unreadable = False

    def begin_turn(self) -> None:
        """Drop the identities of a turn that has ended, or of a replaced stream."""
        self._turn.clear()

    def fragments(self, tool_calls: Optional[List[Any]]) -> Iterator[Tuple[str, Optional[str], str]]:
        """Yield the (id, name, fragment) triples that are the client's to receive."""
        deltas, unattributable, unwritten, unreadable = extract_tool_call_arg_deltas(tool_calls, self._turn)
        if unattributable:
            self._report_unattributable()
        if unwritten:
            self._report_unwritten(*unwritten[0])
        if unreadable:
            self._report_unreadable(unreadable)
        for tool_call_id, tool_name, fragment in deltas:
            # The client has been shown a call the run took up both starting
            # and finishing, so putting it back on the record could only ever
            # report a call it watched succeed as never run.
            if tool_call_id not in self._answered:
                self._unanswered[tool_call_id] = tool_name or self._unanswered.get(tool_call_id)
            yield tool_call_id, tool_name, fragment

    def call_answered(self, tool_call_id: Optional[str]) -> None:
        """Record that the run has taken up a call whose arguments it streamed.

        The run takes a call up only once the model has finished writing every
        call of the turn, so this is where the turn's own numbering ends too.
        Keying that on the run taking a call up, rather than on the next model
        request, is what a cached model response needs: it replays the calls a
        run made without making a request of its own, so a later turn's
        fragment would otherwise resolve against an earlier turn's call.
        """
        self._turn.clear()
        if tool_call_id:
            self._unanswered.pop(tool_call_id, None)
            self._answered.add(tool_call_id)

    def take_unanswered(self) -> List[Tuple[str, Optional[str]]]:
        """The (id, name) pairs of streamed calls the run never took up, once each."""
        unanswered = list(self._unanswered.items())
        self._unanswered.clear()
        return unanswered

    def _report_unattributable(self) -> None:
        """Say once for the stream that argument text arrived naming no call."""
        if self._reported_unattributable:
            return
        self._reported_unattributable = True
        log_warning(
            "A streamed tool call argument fragment carried neither a tool call id nor a provider "
            "stream index, so nothing places it and it is not streamed. The streamed arguments of the "
            "affected call are therefore incomplete, and a subscriber that concatenates them cannot "
            "parse the result. Agno's own record of the call is unaffected, because only the stream "
            f"is short of that text. {self._run_label}"
        )

    def _report_unwritten(self, tool_call_id: Optional[str], tool_name: Optional[str]) -> None:
        """Say once for the stream that a delta's arguments were not text."""
        if self._reported_unwritten:
            return
        self._reported_unwritten = True
        known = ", ".join(part for part in (tool_call_id, tool_name) if part)
        affected = f" ({known})" if known else ""
        log_warning(
            f"A streamed tool call delta{affected} carried its arguments as a structure rather than as "
            "the text the model wrote, so there is no fragment of that text to stream and none is sent. "
            "The streamed arguments of the affected call are therefore incomplete, and a subscriber that "
            "concatenates them cannot parse the result. Agno's own record of the call is unaffected, "
            f"because only the stream is short of that text. {self._run_label}"
        )

    def _report_unreadable(self, shape: str) -> None:
        """Say once for the stream that a batch of deltas could not be read at all."""
        if self._reported_unreadable:
            return
        self._reported_unreadable = True
        log_warning(
            f"A model stream reported its tool calls as a single {shape} rather than as a list of tool "
            "call deltas, which this cannot read, so no argument fragment is streamed for any call that "
            "batch carries. The streamed arguments of those calls are therefore missing altogether, and "
            "a subscriber is left with nothing to concatenate. Agno's own record of the calls is "
            f"unaffected, because only the stream is short of that text. {self._run_label}"
        )


def answer_streamed_tool_calls(
    tool_args_stream: Optional[ToolCallArgsStream],
    tool_executions: Optional[List[ToolExecution]],
) -> None:
    """Strike off the calls the run has taken up, so they are not closed as refused."""
    if tool_args_stream is None:
        return
    for tool_execution in tool_executions or []:
        tool_args_stream.call_answered(tool_execution.tool_call_id)


def take_refused_tool_calls(
    tool_args_stream: Optional[ToolCallArgsStream],
) -> List[ToolExecution]:
    """The calls a client was shown that the run refused, to be told to it.

    Arguments are streamed while the model is still writing them, so a call
    reaches the client before the run has decided whether to make it. One the
    run then declines, by the tool call limit or because the model named a tool
    that does not exist, is never started and never completed, so it is
    reported as having failed rather than left as a call the client waits on
    for good.

    That report is an event and nothing else. The run's own tool list is the
    framework's record of the calls it made, and a call it declined to make is
    not one of them.

    Safe to call at any point a turn's calls have all been decided: a call the
    run took up has already been struck off, and nothing is reported twice.
    """
    if tool_args_stream is None:
        return []
    return [
        ToolExecution(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_call_error=True,
            result=REFUSED_TOOL_CALL_ERROR,
        )
        for tool_call_id, tool_name in tool_args_stream.take_unanswered()
    ]
