from typing import Any, Dict, List, Union

from pydantic import BaseModel

from agno.models.message import Message


def serialize_input(
    input: Union[str, Dict[str, Any], List[Any], BaseModel, List[Message]],
) -> Union[str, Dict[str, Any], List[Any]]:
    """Serialize the input to a string."""
    if isinstance(input, str):
        return input
    elif isinstance(input, dict):
        return input
    elif isinstance(input, list):
        for item in input:
            if isinstance(item, Message):
                item = item.to_dict()
        return input
    elif isinstance(input, BaseModel):
        return input.model_dump_json()
