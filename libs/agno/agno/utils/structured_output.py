from typing import Any, Callable, Dict, Iterator, Optional, Type, Union

from pydantic import BaseModel


def finalize_streamed_structured_output(
    *,
    content_getter: Callable[[], Any],
    output_schema: Optional[Union[Type[BaseModel], Dict]],
    should_parse_structured_output: bool,
    convert_fn: Callable[[], None],
    set_content_fn: Optional[Callable[[Any], None]] = None,
    set_content_type_fn: Optional[Callable[[str], None]] = None,
    stream_events: bool = False,
    build_event_fn: Optional[Callable[[Any, str], Any]] = None,
    emit_fn: Optional[Callable[[Any], Any]] = None,
) -> Iterator[Any]:
    """Finalize streamed structured output and optionally yield one emitted event."""
    content = content_getter()
    if not should_parse_structured_output or content is None or output_schema is None:
        return

    convert_fn()
    parsed_content = content_getter()
    content_type = "dict" if isinstance(output_schema, dict) else output_schema.__name__

    if set_content_fn is not None:
        set_content_fn(parsed_content)
    if set_content_type_fn is not None:
        set_content_type_fn(content_type)

    if stream_events and build_event_fn is not None and emit_fn is not None:
        event_payload = build_event_fn(parsed_content, content_type)
        yield emit_fn(event_payload)
