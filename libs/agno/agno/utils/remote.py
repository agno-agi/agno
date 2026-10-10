import json
from typing import Any, Dict, List, Union

from pydantic import BaseModel

from agno.models.message import Message


def serialize_input(
    input: Union[str, Dict[str, Any], List[Any], BaseModel, List[Message]],
) -> str:
    """Serialize the input to a string."""
    if isinstance(input, str):
        return input
    elif isinstance(input, dict):
        return json.dumps(input)
    elif isinstance(input, list):
        # Local runs accept Message objects and dictionaries in the same conversation.
        return json.dumps([item.to_dict() if isinstance(item, Message) else item for item in input])
    elif isinstance(input, BaseModel):
        return input.model_dump_json()
