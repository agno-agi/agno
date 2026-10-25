"""Deterministic workflow step functions.

Register the ones an application should be able to build with in
``Registry(functions=[...])``; nothing here enters a registry on its own. Each
function consumes the previous step's content, falling back to the workflow
input. Failures are returned as content prefixed with ``Error: `` so a stored
workflow can branch on them; they never raise. File-producing functions return
the data as content and as a file artifact. Use them at a workflow's top level:
a file produced inside a condition, loop or parallel step is dropped while the
content still flows.
"""

import csv
import io
import json
import re
from typing import Any, List

from pydantic import BaseModel

from agno.media import File
from agno.workflow.types import StepInput, StepOutput

_URL_PATTERN = re.compile(r"https?://[^\s<>\"')\]]+")
_TABLE_ROW_CAP = 50
_ERROR_PREFIX = "Error: "


def _error(message: str) -> str:
    """A step failure a workflow can branch on instead of dying on."""
    return f"{_ERROR_PREFIX}{message}"


def _step_text(step_input: StepInput) -> str:
    """The text a function step operates on: the previous step's output, else the workflow input."""
    content = step_input.previous_step_content
    if content is None:
        return step_input.get_input_as_string() or ""
    if isinstance(content, BaseModel):
        return content.model_dump_json(indent=2, exclude_none=True)
    if isinstance(content, (dict, list)):
        return json.dumps(content, indent=2, default=str, ensure_ascii=False)
    return str(content)


_NO_JSON = object()


def _json_payload(text: str) -> Any:
    """Decode the largest JSON object or array in text; ``_NO_JSON`` when none decodes.

    Largest, not first: a gathering agent's ``[1]`` citations and ``[ ]`` checkboxes decode too.
    """
    decoder = json.JSONDecoder()
    best_span, best_value, skip_until = 0, _NO_JSON, 0
    for match in re.finditer(r"[\[{]", text):
        start = match.start()
        if start < skip_until:  # inside a value already decoded
            continue
        try:
            value, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            continue
        if end - start > best_span:
            best_span, best_value = end - start, value
        skip_until = end
    return best_value


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _table_cell(cell: str) -> str:
    return cell.strip().replace("|", "\\|").replace("\r\n", "\n").replace("\n", "<br>")


def extract_json(step_input: StepInput) -> str:
    """Return the largest JSON object or array in the previous step's output, validated and pretty-printed.

    Returns ``Error: ...`` when the previous step produced no parseable JSON. Put this
    step between a gathering agent and any step that needs structured input. An upstream
    ``Error: `` passes through unchanged.
    """
    text = _step_text(step_input)
    if text.startswith(_ERROR_PREFIX):
        return text
    value = _json_payload(text)
    if value is _NO_JSON:
        return _error("no valid JSON object or array in the previous step's output")
    return json.dumps(value, indent=2, ensure_ascii=False)


def extract_urls(step_input: StepInput) -> str:
    """Return the URLs found in the previous step's output, deduplicated in order, one per line.

    Returns ``Error: ...`` when it holds no URL. An upstream ``Error: `` passes through unchanged.
    """
    text = _step_text(step_input)
    if text.startswith(_ERROR_PREFIX):
        return text
    urls = dict.fromkeys(url.rstrip(".,;:!?`*") for url in _URL_PATTERN.findall(text))
    if not urls:
        return _error("no URLs in the previous step's output")
    return "\n".join(urls)


def json_to_csv(step_input: StepInput) -> StepOutput:
    """Convert a JSON array of objects from the previous step's output into a data.csv file artifact.

    Columns are the union of the objects' keys in first-appearance order; nested values are
    JSON-encoded in their cell. The CSV is also the step's content, so a following step such as
    csv_to_markdown_table receives the data rather than a summary of it. Returns ``Error: ...``
    when the previous step holds no JSON array of objects; an upstream ``Error: `` passes
    through unchanged.
    """
    text = _step_text(step_input)
    if text.startswith(_ERROR_PREFIX):
        return StepOutput(content=text)
    value = _json_payload(text)
    if isinstance(value, dict):
        # Tolerate a single-array wrapper like {"rows": [...]}.
        arrays = [item for item in value.values() if isinstance(item, list)]
        if len(arrays) == 1:
            value = arrays[0]
    if value is _NO_JSON or not isinstance(value, list) or not value or not all(isinstance(r, dict) for r in value):
        return StepOutput(content=_error("expected a JSON array of objects in the previous step's output"))
    header: List[str] = []
    for row in value:
        for key in row:
            if key not in header:
                header.append(key)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=header, extrasaction="ignore")
    writer.writeheader()
    for row in value:
        writer.writerow({key: _cell(row.get(key)) for key in header})
    data = buffer.getvalue()
    return StepOutput(
        content=data,
        files=[File(content=data.encode(), mime_type="text/csv", filename="data.csv")],
    )


def csv_to_markdown_table(step_input: StepInput) -> str:
    """Render CSV text from the previous step's output as a markdown table, capped at 50 data rows.

    Pairs with json_to_csv. Returns ``Error: ...`` when the input is not CSV with a header
    row and at least one data row, and passes an upstream ``Error: `` through unchanged.
    """
    text = _step_text(step_input)
    if text.startswith(_ERROR_PREFIX):
        return text  # a failure upstream stays one failure, not two

    def line(cells: List[str]) -> str:
        return "| " + " | ".join(_table_cell(cell) for cell in cells) + " |"

    try:
        rows = (row for row in csv.reader(io.StringIO(text), strict=True) if row)
        header = next(rows, None)
        if header is None:
            return _error("expected CSV with a header row and at least one data row")
        lines = [line(header), "| " + " | ".join("---" for _ in header) + " |"]
        count = 0
        for row in rows:
            count += 1
            if count <= _TABLE_ROW_CAP:
                lines.append(line(row))
    except csv.Error:
        return _error("invalid CSV or a field exceeds the CSV parser limit")
    if count == 0:
        return _error("expected CSV with a header row and at least one data row")
    if count > _TABLE_ROW_CAP:
        lines.append(f"... {count - _TABLE_ROW_CAP} more rows")
    return "\n".join(lines)


def content_to_file(step_input: StepInput) -> StepOutput:
    """Attach the previous step's output unchanged as an output.md file artifact.

    The content also flows through as the step's output, so this works as a final
    publish step without breaking the chain. Returns ``Error: ...`` when the previous step
    produced no content; an upstream ``Error: `` passes through unchanged, with no file.
    """
    text = _step_text(step_input)
    if text.startswith(_ERROR_PREFIX):
        return StepOutput(content=text)
    if not text.strip():
        return StepOutput(content=_error("previous step produced no content to save"))
    return StepOutput(
        content=text,
        files=[File(content=text.encode(), mime_type="text/markdown", filename="output.md")],
    )


async def aextract_json(step_input: StepInput) -> str:
    """Async variant of extract_json; performs no I/O."""
    return extract_json(step_input)


async def aextract_urls(step_input: StepInput) -> str:
    """Async variant of extract_urls; performs no I/O."""
    return extract_urls(step_input)


async def ajson_to_csv(step_input: StepInput) -> StepOutput:
    """Async variant of json_to_csv; performs no I/O."""
    return json_to_csv(step_input)


async def acsv_to_markdown_table(step_input: StepInput) -> str:
    """Async variant of csv_to_markdown_table; performs no I/O."""
    return csv_to_markdown_table(step_input)


async def acontent_to_file(step_input: StepInput) -> StepOutput:
    """Async variant of content_to_file; performs no I/O."""
    return content_to_file(step_input)


__all__ = [
    "extract_json",
    "extract_urls",
    "json_to_csv",
    "csv_to_markdown_table",
    "content_to_file",
    "aextract_json",
    "aextract_urls",
    "ajson_to_csv",
    "acsv_to_markdown_table",
    "acontent_to_file",
]
