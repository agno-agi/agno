import dataclasses
from typing import Any, Optional, Sequence, TypeVar, Union

from surrealdb import BlockingHttpSurrealConnection, BlockingWsSurrealConnection, Surreal

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
) -> Union[list, dict]:
    try:
        response = client.query(query, vars)
        logger.debug(f"Query: {query} with {vars}, Response: {response}")
    except Exception as e:
        logger.error(f"Query execution error: {query} with {vars}, Error: {e}")
        raise e
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
            return [record_type(**x) for x in response]
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
    elif not isinstance(response, list):
        if dataclasses.is_dataclass(record_type) and hasattr(record_type, "from_dict"):
            return getattr(record_type, "from_dict").__call__(response)
        else:
            return record_type(**response)
    else:
        raise ValueError(f"Unexpected response type: {type(response)}")
