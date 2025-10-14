from datetime import date, datetime, timedelta
from textwrap import dedent
from typing import Any, Callable, Dict, List, Optional, Union

from surrealdb import BlockingHttpSurrealConnection, BlockingWsSurrealConnection, RecordID

from agno.db.base import SessionType
from agno.db.surrealdb import utils
from agno.db.surrealdb.models import desurrealize_session, surrealize_dates
from agno.db.surrealdb.queries import WhereClause
from agno.utils.log import log_error


def get_all_sessions_for_metrics_calculation(
    client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection],
    table: str,
    start_timestamp: Optional[datetime] = None,
    end_timestamp: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """
    Get all sessions of all types (agent, team, workflow) as raw dictionaries.

    Args:
        start_timestamp (Optional[int]): The start timestamp to filter by. Defaults to None.
        end_timestamp (Optional[int]): The end timestamp to filter by. Defaults to None.

    Returns:
        List[Dict[str, Any]]: List of session dictionaries with session_type field.

    Raises:
        Exception: If an error occurs during retrieval.
    """
    where = WhereClause()

    # starting_date
    if start_timestamp is not None:
        where = where.and_("created_at", start_timestamp, ">=")

    # ending_date
    if end_timestamp is not None:
        where = where.and_("created_at", end_timestamp, "<=")

    where_clause, where_vars = where.build()

    # Query
    query = dedent(f"""
        SELECT *
        FROM {table}
        {where_clause}
    """)

    results = utils.query(client, query, where_vars, dict)
    return [desurrealize_session(x) for x in results]


def get_metrics_calculation_starting_date(
    client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection], table: str, get_sessions: Callable
) -> Optional[date]:
    """Get the first date for which metrics calculation is needed:

    1. If there are metrics records, return the date of the first day without a complete metrics record.
    2. If there are no metrics records, return the date of the first recorded session.
    3. If there are no metrics records and no sessions records, return None.

    Args:
        table (Table): The table to get the starting date for.

    Returns:
        Optional[date]: The starting date for which metrics calculation is needed.
    """
    query = dedent(f"""
        SELECT * FROM ONLY {table}
        ORDER BY date DESC
        LIMIT 1
    """)
    result = utils.query_one(client, query, {}, dict)
    if result:
        # 1. Return the date of the first day without a complete metrics record
        result_date = result["date"]
        assert isinstance(result_date, datetime)
        result_date = result_date.date()

        if result.get("completed"):
            return result_date + timedelta(days=1)
        else:
            return result_date

    # 2. No metrics records. Return the date of the first recorded session
    first_session, _ = get_sessions(
        session_type=SessionType.AGENT,  # this is ignored because of component_id=None and deserialize=False
        sort_by="created_at",
        sort_order="asc",
        limit=1,
        component_id=None,
        deserialize=False,
    )
    assert isinstance(first_session, list)

    first_session_date = first_session[0]["created_at"] if first_session else None

    # 3. No metrics records and no sessions records. Return None
    if first_session_date is None:
        return None

    assert isinstance(first_session_date, datetime)
    return first_session_date.date()


def bulk_upsert_metrics(
    client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection],
    table: str,
    metrics_records: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Bulk upsert metrics into the database.

    Args:
        table (Table): The table to upsert into.
        metrics_records (List[Dict[str, Any]]): The list of metrics records to upsert.

    Returns:
        list[dict]: The upserted metrics records.
    """
    if not metrics_records:
        return []

    metrics_records = [surrealize_dates(x) for x in metrics_records]

    try:
        results = []
        for metric in metrics_records:
            result = utils.query_one(
                client,
                "UPSERT $record CONTENT $content",
                {"record": RecordID(table, metric["id"]), "content": metric},
                dict,
            )
            if result:
                results.append(result)
        return results

    except Exception as e:
        log_error(f"Error upserting metrics: {e}")

    return []
