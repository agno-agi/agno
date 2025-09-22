import dataclasses
from typing import Any, Sequence, TypeVar

from surrealdb import BlockingHttpSurrealConnection, BlockingWsSurrealConnection, Surreal

from agno.utils.log import logger

RecordType = TypeVar("RecordType")


def build_client(
    url: str, creds: dict[str, str], ns: str, db: str
) -> BlockingHttpSurrealConnection | BlockingWsSurrealConnection:
    client = Surreal(url=url)
    client.signin(creds)
    client.use(namespace=ns, database=db)
    return client


def _query_aux(
    client: BlockingWsSurrealConnection | BlockingHttpSurrealConnection,
    query: str,
    vars: dict[str, Any],
) -> list | dict:
    try:
        response = client.query(query, vars)
        logger.debug(f"Query: {query}, Response: {response}")
    except Exception as e:
        logger.error(f"Query execution error: {e}")
        raise e
    return response


def query(
    client: BlockingWsSurrealConnection | BlockingHttpSurrealConnection,
    query: str,
    vars: dict[str, Any],
    record_type: type[RecordType],
) -> Sequence[RecordType]:
    response = _query_aux(client, query, vars)
    if isinstance(response, list):
        if dataclasses.is_dataclass(record_type) and hasattr(record_type, "from_dict"):
            return [getattr(record_type, "from_dict").__call__(x) for x in response]
        else:
            return [record_type(**x) for x in response]
    else:
        raise ValueError(f"Unexpected response type: {type(response)}")


def query_one(
    client: BlockingWsSurrealConnection | BlockingHttpSurrealConnection,
    query: str,
    vars: dict[str, Any],
    record_type: type[RecordType],
) -> RecordType:
    response = _query_aux(client, query, vars)
    if not isinstance(response, list):
        if dataclasses.is_dataclass(record_type) and hasattr(record_type, "from_dict"):
            return getattr(record_type, "from_dict").__call__(response)
        else:
            return record_type(**response)
    else:
        raise ValueError(f"Unexpected response type: {type(response)}")
