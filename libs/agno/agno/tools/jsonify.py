import json
from os import getenv
from typing import Any, Dict, List, Optional, Union

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger


class JsonifyTools(Toolkit):
    """
    Jsonify keeps datasets from the live web current. A pipeline runs on a schedule,
    repairs itself when a source changes, and publishes the result as a dataset.
    Every dataset has a serve URL that returns its latest rows as JSON, so an agent
    reads maintained data instead of re-scraping.

    Serve URLs are secrets. Keep them server-side and out of prompts.

    Args:
        datasets (Optional[Union[str, Dict[str, str]]]): Serve URL of one dataset, or a
            mapping of dataset name to serve URL. Defaults to the JSONIFY_SERVE_URL
            environment variable, registered under the name "default".
        enable_get_rows (bool): Enable reading rows from a dataset. Default is True.
        enable_get_dataset_info (bool): Enable reading dataset metadata and columns. Default is True.
        all (bool): Enable all tools. Overrides individual flags when True. Default is False.
        timeout (int): Per-request HTTP timeout in seconds. Defaults to 30.
    """

    def __init__(
        self,
        datasets: Optional[Union[str, Dict[str, str]]] = None,
        enable_get_rows: bool = True,
        enable_get_dataset_info: bool = True,
        all: bool = False,
        timeout: int = 30,
        **kwargs,
    ):
        if datasets is None:
            datasets = getenv("JSONIFY_SERVE_URL")
        if not datasets:
            raise ValueError("JSONIFY_SERVE_URL environment variable or datasets parameter must be set")
        if isinstance(datasets, str):
            datasets = {"default": datasets}
        self.datasets: Dict[str, str] = dict(datasets)

        tools: List[Any] = []
        async_tools: List[tuple] = []
        if all or enable_get_rows:
            tools.append(self.get_jsonify_rows)
            async_tools.append((self.aget_jsonify_rows, "get_jsonify_rows"))
        if all or enable_get_dataset_info:
            tools.append(self.get_jsonify_dataset_info)
            async_tools.append((self.aget_jsonify_dataset_info, "get_jsonify_dataset_info"))

        super().__init__(name="jsonify_tools", tools=tools, async_tools=async_tools, timeout=timeout, **kwargs)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _serve_url(self, dataset: Optional[str]) -> str:
        if dataset is None:
            if len(self.datasets) == 1:
                return next(iter(self.datasets.values()))
            raise ValueError(f"dataset must be one of: {', '.join(sorted(self.datasets))}")
        if dataset not in self.datasets:
            raise ValueError(f"Unknown dataset '{dataset}'. Available: {', '.join(sorted(self.datasets))}")
        return self.datasets[dataset]

    @staticmethod
    def _rows_params(
        limit: int,
        offset: int,
        columns: Optional[List[str]],
        filters: Optional[Dict[str, str]],
        version: Optional[int],
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if columns:
            params["columns"] = ",".join(columns)
        if version is not None:
            params["version"] = version
        for column, value in (filters or {}).items():
            params[f"filter[{column}]"] = value
        return params

    @staticmethod
    def _format_rows(data: Dict[str, Any]) -> str:
        return json.dumps(
            {
                "dataset_name": data.get("dataset_name"),
                "version": data.get("version"),
                "updated_at": data.get("updated_at"),
                "row_count": data.get("row_count"),
                "has_more": data.get("has_more", False),
                "next_offset": data.get("next_offset"),
                "rows": data.get("rows", []),
            }
        )

    @staticmethod
    def _format_info(data: Dict[str, Any]) -> str:
        rows = data.get("rows", [])
        columns = [c for c in rows[0] if c == "_row_id" or not c.startswith("_")] if rows else []
        return json.dumps(
            {
                "dataset_name": data.get("dataset_name"),
                "table": data.get("table"),
                "version": data.get("version"),
                "updated_at": data.get("updated_at"),
                "columns": columns,
            }
        )

    def _fetch(self, dataset: Optional[str], params: Dict[str, Any]) -> Dict[str, Any]:
        response = httpx.get(self._serve_url(dataset), params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    async def _afetch(self, dataset: Optional[str], params: Dict[str, Any]) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(self._serve_url(dataset), params=params)
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def get_jsonify_rows(
        self,
        dataset: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        columns: Optional[List[str]] = None,
        filters: Optional[Dict[str, str]] = None,
        version: Optional[int] = None,
    ) -> str:
        """Use this function to read rows from a Jsonify dataset. Rows are the latest
        published output of a maintained pipeline, so they are current without scraping.

        Args:
            dataset (Optional[str]): Name of the dataset to read. Omit when only one is configured.
            limit (int): Rows per page, 1 to 10000. Defaults to 100.
            offset (int): Rows to skip. Use next_offset from a previous call to page. Defaults to 0.
            columns (Optional[List[str]]): Column names to return. Omit for all columns.
            filters (Optional[Dict[str, str]]): Exact, case-sensitive column value matches, combined with AND. Up to 10.
            version (Optional[int]): Dataset version to read. Pass the version from a previous page for consistent paging.

        Returns:
            str: JSON string with dataset_name, version, updated_at, row_count, has_more, next_offset and rows.
        """
        try:
            params = self._rows_params(limit, offset, columns, filters, version)
            log_debug(f"Reading Jsonify dataset {dataset or 'default'} with {params}")
            return self._format_rows(self._fetch(dataset, params))
        except Exception as e:
            logger.exception(e)
            return f"Error reading Jsonify dataset: {e}"

    async def aget_jsonify_rows(
        self,
        dataset: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        columns: Optional[List[str]] = None,
        filters: Optional[Dict[str, str]] = None,
        version: Optional[int] = None,
    ) -> str:
        """Use this function to read rows from a Jsonify dataset. Rows are the latest
        published output of a maintained pipeline, so they are current without scraping.

        Args:
            dataset (Optional[str]): Name of the dataset to read. Omit when only one is configured.
            limit (int): Rows per page, 1 to 10000. Defaults to 100.
            offset (int): Rows to skip. Use next_offset from a previous call to page. Defaults to 0.
            columns (Optional[List[str]]): Column names to return. Omit for all columns.
            filters (Optional[Dict[str, str]]): Exact, case-sensitive column value matches, combined with AND. Up to 10.
            version (Optional[int]): Dataset version to read. Pass the version from a previous page for consistent paging.

        Returns:
            str: JSON string with dataset_name, version, updated_at, row_count, has_more, next_offset and rows.
        """
        try:
            params = self._rows_params(limit, offset, columns, filters, version)
            log_debug(f"Reading Jsonify dataset {dataset or 'default'} with {params}")
            return self._format_rows(await self._afetch(dataset, params))
        except Exception as e:
            logger.exception(e)
            return f"Error reading Jsonify dataset: {e}"

    def get_jsonify_dataset_info(self, dataset: Optional[str] = None) -> str:
        """Use this function to get a Jsonify dataset's name, version, last update time
        and column names before reading rows from it.

        Args:
            dataset (Optional[str]): Name of the dataset. Omit when only one is configured.

        Returns:
            str: JSON string with dataset_name, table, version, updated_at and columns.
        """
        try:
            return self._format_info(self._fetch(dataset, {"limit": 1}))
        except Exception as e:
            logger.exception(e)
            return f"Error reading Jsonify dataset info: {e}"

    async def aget_jsonify_dataset_info(self, dataset: Optional[str] = None) -> str:
        """Use this function to get a Jsonify dataset's name, version, last update time
        and column names before reading rows from it.

        Args:
            dataset (Optional[str]): Name of the dataset. Omit when only one is configured.

        Returns:
            str: JSON string with dataset_name, table, version, updated_at and columns.
        """
        try:
            return self._format_info(await self._afetch(dataset, {"limit": 1}))
        except Exception as e:
            logger.exception(e)
            return f"Error reading Jsonify dataset info: {e}"
