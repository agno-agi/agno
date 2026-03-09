import dataclasses
from typing import Any, Dict, Optional, Sequence, TypeVar, Union, cast

from surrealdb import BlockingHttpSurrealConnection, BlockingWsSurrealConnection, Surreal

from agno.db.schemas.culture import CulturalKnowledge
from agno.utils.log import logger

RecordType = TypeVar("RecordType")


def build_client(
    url: str, creds: dict[str, str], ns: str, db: str
) -> Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection]:
    client = Surreal(url=url)
    client.signin(creds)
    client.use(namespace=ns, database=db)
    return client


def _query_aux(
    client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection],
    query: str,
    vars: dict[str, Any],
) -> Union[list, dict, str, int]:
    try:
        response = client.query(query, vars)
    except Exception as e:
        msg = f"!! Query execution error: {query} with {vars}, Error: {e}"
        logger.error(msg)
        raise RuntimeError(msg)
    return response


def query(
    client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection],
    query: str,
    vars: dict[str, Any],
    record_type: type[RecordType],
) -> Sequence[RecordType]:
    response = _query_aux(client, query, vars)
    if isinstance(response, list):
        if dataclasses.is_dataclass(record_type) and hasattr(record_type, "from_dict"):
            return [getattr(record_type, "from_dict").__call__(x) for x in response]
        else:
            result: list[RecordType] = []
            for x in response:
                if isinstance(x, dict):
                    result.append(record_type(**x))
                else:
                    result.append(record_type.__call__(x))
            return result
    else:
        raise ValueError(f"Unexpected response type: {type(response)}")


def query_one(
    client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection],
    query: str,
    vars: dict[str, Any],
    record_type: type[RecordType],
) -> Optional[RecordType]:
    response = _query_aux(client, query, vars)
    if response is None:
        return None
    elif isinstance(response, str):
        return None
    elif not isinstance(response, list):
        if dataclasses.is_dataclass(record_type) and hasattr(record_type, "from_dict"):
            return getattr(record_type, "from_dict").__call__(response)
        elif isinstance(response, dict):
            return record_type(**response)
        else:
            return record_type.__call__(response)
    elif isinstance(response, list):
        # Handle list responses - SurrealDB might return a list with a single element
        if len(response) == 1 and isinstance(response[0], dict):
            result = response[0]
            if dataclasses.is_dataclass(record_type) and hasattr(record_type, "from_dict"):
                return getattr(record_type, "from_dict").__call__(result)
            elif record_type is dict:
                return cast(RecordType, result)
            else:
                return record_type(**result)
        elif len(response) == 0:
            return None
        else:
            raise ValueError(f"Expected single record, got {len(response)} records: {response}")
    else:
        raise ValueError(f"Unexpected response type: {type(response)}")


# -- Cultural Knowledge util methods --


def serialize_cultural_knowledge_for_db(cultural_knowledge: CulturalKnowledge) -> Dict[str, Any]:
    """Serialize a CulturalKnowledge object for database storage.

    Converts the model's separate content, categories, and notes fields
    into a single dict for the database content field.

    Args:
        cultural_knowledge (CulturalKnowledge): The cultural knowledge object to serialize.

    Returns:
        Dict[str, Any]: A dictionary with content, categories, and notes.
    """
    content_dict: Dict[str, Any] = {}
    if cultural_knowledge.content is not None:
        content_dict["content"] = cultural_knowledge.content
    if cultural_knowledge.categories is not None:
        content_dict["categories"] = cultural_knowledge.categories
    if cultural_knowledge.notes is not None:
        content_dict["notes"] = cultural_knowledge.notes

    return content_dict if content_dict else {}


def deserialize_cultural_knowledge_from_db(db_row: Dict[str, Any]) -> CulturalKnowledge:
    """Deserialize a database row to a CulturalKnowledge object.

    The database stores content as a dict containing content, categories, and notes.
    This method extracts those fields and converts them back to the model format.

    Args:
        db_row (Dict[str, Any]): The database row as a dictionary.

    Returns:
        CulturalKnowledge: The cultural knowledge object.
    """
    # Extract content, categories, and notes from the content field
    content_json = db_row.get("content", {}) or {}

    return CulturalKnowledge.from_dict(
        {
            "id": db_row.get("id"),
            "name": db_row.get("name"),
            "summary": db_row.get("summary"),
            "content": content_json.get("content"),
            "categories": content_json.get("categories"),
            "notes": content_json.get("notes"),
            "metadata": db_row.get("metadata"),
            "input": db_row.get("input"),
            "created_at": db_row.get("created_at"),
            "updated_at": db_row.get("updated_at"),
            "agent_id": db_row.get("agent_id"),
            "team_id": db_row.get("team_id"),
        }
    )
