"""The vendored Tinker acceptance check -- a private test oracle, not public API.

Mirrors rl-tutor's `_parse_conversations` / `_dataset_size_error` (tutor/
tinker_tools.py): exactly {"messages"} at top level and exactly {"role", "content"}
per message -- strict set equality, an unknown key REJECTS THE FILE, it is not
dropped; roles {system, user, assistant}; content a non-blank string; at least one
user message; last message assistant; 320 conversations; 1 MiB utf-8.
"""

import json
from pathlib import Path
from typing import Union

MAX_CONVERSATIONS = 320  # BATCH_SIZE (8) * MAX_STEPS (40) in the consumer
MAX_DATASET_BYTES = 1024 * 1024

_MESSAGE_ROLES = frozenset({"system", "user", "assistant"})


def validate_sft_jsonl(path: Union[str, Path]) -> int:
    """Validate an exported file exactly as the strictest checked consumer would.

    Returns the number of conversations; raises ValueError on the first violation.
    """
    text = Path(path).read_text(encoding="utf-8")
    size = len(text.encode("utf-8"))
    if size > MAX_DATASET_BYTES:
        raise ValueError(f"dataset is {size} bytes; the limit is {MAX_DATASET_BYTES} bytes")
    if not text.strip():
        raise ValueError("dataset must contain at least one conversation")
    # Split on "\n" only, matching the canonical writer: splitlines() also breaks on
    # U+2028/U+2029/U+0085, which json.dumps(ensure_ascii=False) emits unescaped.
    lines = text.strip().split("\n")
    if len(lines) > MAX_CONVERSATIONS:
        raise ValueError(f"dataset has {len(lines)} conversations; the limit is {MAX_CONVERSATIONS}")
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            raise ValueError(f"line {line_number} is blank; JSONL requires one object per line")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"line {line_number} is not valid JSON: {exc.msg}") from exc
        if not isinstance(value, dict) or set(value) != {"messages"}:
            raise ValueError(f"line {line_number} must contain only a messages field")
        messages = value["messages"]
        if not isinstance(messages, list) or not messages:
            raise ValueError(f"line {line_number} must have a non-empty messages list")
        for message_number, message in enumerate(messages, start=1):
            prefix = f"line {line_number}, message {message_number}"
            if not isinstance(message, dict) or set(message) != {"role", "content"}:
                raise ValueError(f"{prefix} must contain only role and content")
            role = message["role"]
            content = message["content"]
            if not isinstance(role, str) or role not in _MESSAGE_ROLES:
                raise ValueError(f"{prefix} has unsupported role {role!r}")
            if not isinstance(content, str) or not content.strip():
                raise ValueError(f"{prefix} content must be a non-empty string")
        if not any(message["role"] == "user" for message in messages):
            raise ValueError(f"line {line_number} must contain a user message")
        if messages[-1]["role"] != "assistant":
            raise ValueError(f"line {line_number} must end with an assistant message")
    return len(lines)
