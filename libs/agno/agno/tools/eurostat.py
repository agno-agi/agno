"""
Eurostat toolkit for real-time European Union official statistics.

Eurostat (https://ec.europa.eu/eurostat) is the statistical office of the
European Union, publishing harmonised economic and demographic data across
member states. This toolkit queries Eurostat's public dissemination API
directly, so an agent gets actual published figures (GDP, unemployment,
inflation, population, ...) instead of guessing from training data.

No API key or registration is required -- the API is fully public.

Note:
- Eurostat dataset codes are terse and non-obvious (e.g. "une_rt_m" for the
  monthly unemployment rate). `get_indicator` exposes a small set of common
  indicators under friendly names; `get_dataset` accepts any raw Eurostat
  dataset code plus dimension filters for anything not covered by that list.
  Codes can be browsed at https://ec.europa.eu/eurostat/databrowser.
- Responses come back from Eurostat in JSON-stat format, which encodes values
  as a flat, index-addressed array rather than a list of records. This
  toolkit unpacks that into a list of {dimension: label, ..., "value": ...}
  records, which is far easier for a model to reason about directly.
"""

from typing import Any, Dict, List, Optional, Tuple

try:
    import httpx
except ImportError:
    raise ImportError("`httpx` not installed. Please install it via `pip install httpx`.")

from agno.tools import Toolkit
from agno.utils.log import log_info, logger

BASE_URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"

# Friendly names for a handful of commonly requested indicators, mapped to
# their Eurostat dataset code and default dimension filters. Each entry was
# verified against the live Eurostat API before being added here.
KNOWN_INDICATORS: Dict[str, Dict[str, Any]] = {
    "unemployment_rate": {
        "dataset": "une_rt_m",
        "filters": {"sex": "T", "age": "TOTAL", "s_adj": "SA", "unit": "PC_ACT"},
        "description": "Monthly seasonally-adjusted unemployment rate (% of active population).",
    },
    "inflation_rate": {
        "dataset": "prc_hicp_manr",
        "filters": {"coicop": "CP00", "unit": "RCH_A"},
        "description": "Monthly HICP annual rate of change (inflation), all-items.",
    },
    "gdp": {
        "dataset": "nama_10_gdp",
        "filters": {"unit": "CLV10_MEUR", "na_item": "B1GQ"},
        "description": "Annual GDP at market prices, chain-linked volumes (million EUR, 2010 reference).",
    },
    "population": {
        "dataset": "demo_pjan",
        "filters": {"sex": "T", "age": "TOTAL"},
        "description": "Population on 1 January, total.",
    },
}


class EurostatTools(Toolkit):
    """Toolkit for querying live European Union official statistics from Eurostat.

    Args:
        timeout (float): Per-request HTTP timeout in seconds. Default is 30.
        enable_list_indicators (bool): Enable the `list_indicators` tool. Default is True.
        enable_get_indicator (bool): Enable the `get_indicator` tool. Default is True.
        enable_get_dataset (bool): Enable the `get_dataset` tool. Default is True.
        all (bool): Enable all tools regardless of the individual flags. Default is False.
    """

    def __init__(
        self,
        timeout: float = 30.0,
        enable_list_indicators: bool = True,
        enable_get_indicator: bool = True,
        enable_get_dataset: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.timeout = httpx.Timeout(timeout)

        # sync tools: used by agent.run() and agent.print_response()
        # async tools: used by agent.arun() and agent.aprint_response()
        tools: List[Any] = []
        async_tools: List[Tuple[Any, str]] = []

        if all or enable_list_indicators:
            tools.append(self.list_indicators)
            async_tools.append((self.alist_indicators, "list_indicators"))
        if all or enable_get_indicator:
            tools.append(self.get_indicator)
            async_tools.append((self.aget_indicator, "get_indicator"))
        if all or enable_get_dataset:
            tools.append(self.get_dataset)
            async_tools.append((self.aget_dataset, "get_dataset"))

        name = kwargs.pop("name", "eurostat_tools")
        super().__init__(name=name, tools=tools, async_tools=async_tools, **kwargs)

    # ---------------------------------------------------------------------
    # Helpers (pure -- no I/O)
    # ---------------------------------------------------------------------
    @staticmethod
    def _http_error(exc: "httpx.HTTPStatusError") -> Dict[str, str]:
        status = exc.response.status_code
        if status == 404:
            return {"error": "Dataset code not found, or no data matches the given filters."}
        if status == 400:
            return {"error": "Invalid dataset code or filter value. Check dimension codes and try again."}
        if status == 429:
            return {"error": "Eurostat rate limit exceeded. Try again later."}
        return {"error": f"Eurostat API error: {status}."}

    @staticmethod
    def _parse_jsonstat(data: Dict[str, Any]) -> Dict[str, Any]:
        """Unpack a Eurostat JSON-stat response into a flat list of records.

        JSON-stat encodes the result as a single flat `value` map keyed by a
        computed flat index, plus a `dimension` block describing the category
        labels for each axis. This walks the dimension sizes to recover, for
        every stored value, which category label it corresponds to on each axis.
        """
        dimension = data.get("dimension", {})
        ids: List[str] = data.get("id", [])
        sizes: List[int] = data.get("size", [])
        values: Dict[str, float] = data.get("value", {})
        title = data.get("label", "")
        source = data.get("source", "")

        if not ids or not sizes or not values:
            return {"title": title, "source": source, "records": []}

        # categories[axis] = labels in index order for that dimension
        categories: List[List[str]] = []
        for dim_id in ids:
            dim_info = dimension.get(dim_id, {})
            category = dim_info.get("category", {})
            index = category.get("index", {})
            labels = category.get("label", {})
            ordered_codes: List[Optional[str]] = [None] * len(index)
            for code, pos in index.items():
                ordered_codes[pos] = code
            categories.append([labels.get(code, code) for code in ordered_codes if code is not None])

        records: List[Dict[str, Any]] = []
        for flat_index_str, value in values.items():
            remainder = int(flat_index_str)
            # JSON-stat uses row-major order over `size`, with the last dimension fastest-varying.
            positions = [0] * len(sizes)
            for axis in range(len(sizes) - 1, -1, -1):
                positions[axis] = remainder % sizes[axis]
                remainder //= sizes[axis]
            record: Dict[str, Any] = {dim_id: categories[axis][positions[axis]] for axis, dim_id in enumerate(ids)}
            record["value"] = value
            records.append(record)

        return {"title": title, "source": source, "records": records}

    def _request(self, dataset_code: str, params: Dict[str, Any]) -> Dict[str, Any]:
        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(f"{BASE_URL}/{dataset_code}", params=params)
            response.raise_for_status()
            return response.json()

    async def _arequest(self, dataset_code: str, params: Dict[str, Any]) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{BASE_URL}/{dataset_code}", params=params)
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _build_params(geo: Optional[str], since: Optional[str], filters: Optional[Dict[str, str]]) -> Dict[str, Any]:
        params: Dict[str, Any] = {"format": "JSON", "lang": "en"}
        if filters:
            params.update(filters)
        if geo:
            params["geo"] = geo
        if since:
            params["sinceTimePeriod"] = since
        return params

    # ---------------------------------------------------------------------
    # Tools
    # ---------------------------------------------------------------------
    def list_indicators(self) -> Dict[str, Any]:
        """List the known-indicator shortcuts available via `get_indicator`.

        Returns:
            Dict[str, Any]: Mapping of indicator name to its description and
            underlying Eurostat dataset code.
        """
        return {
            name: {"dataset": info["dataset"], "description": info["description"]}
            for name, info in KNOWN_INDICATORS.items()
        }

    async def alist_indicators(self) -> Dict[str, Any]:
        """List the known-indicator shortcuts available via `get_indicator` (async).

        Returns:
            Dict[str, Any]: Mapping of indicator name to its description and
            underlying Eurostat dataset code.
        """
        return self.list_indicators()

    def get_indicator(self, indicator: str, geo: str, since: Optional[str] = None) -> Dict[str, Any]:
        """Get a well-known EU statistical indicator for a country or region.

        Args:
            indicator (str): One of the names returned by `list_indicators`
                (e.g. "unemployment_rate", "inflation_rate", "gdp", "population").
            geo (str): Eurostat geo code, e.g. "DE" (Germany), "FR" (France),
                "EU27_2020" (European Union, 27 members).
            since (Optional[str]): Only return observations from this period
                onward, e.g. "2020" or "2024-01". Defaults to Eurostat's full history.

        Returns:
            Dict[str, Any]: Title, source and a list of {..., "value"} records,
            one per time period, or an error.
        """
        info = KNOWN_INDICATORS.get(indicator)
        if info is None:
            return {"error": f"Unknown indicator '{indicator}'. Call list_indicators() for the available names."}
        return self.get_dataset(info["dataset"], geo=geo, since=since, filters=info["filters"])

    async def aget_indicator(self, indicator: str, geo: str, since: Optional[str] = None) -> Dict[str, Any]:
        """Get a well-known EU statistical indicator for a country or region (async).

        Args:
            indicator (str): One of the names returned by `list_indicators`
                (e.g. "unemployment_rate", "inflation_rate", "gdp", "population").
            geo (str): Eurostat geo code, e.g. "DE" (Germany), "FR" (France),
                "EU27_2020" (European Union, 27 members).
            since (Optional[str]): Only return observations from this period
                onward, e.g. "2020" or "2024-01". Defaults to Eurostat's full history.

        Returns:
            Dict[str, Any]: Title, source and a list of {..., "value"} records,
            one per time period, or an error.
        """
        info = KNOWN_INDICATORS.get(indicator)
        if info is None:
            return {"error": f"Unknown indicator '{indicator}'. Call list_indicators() for the available names."}
        return await self.aget_dataset(info["dataset"], geo=geo, since=since, filters=info["filters"])

    def get_dataset(
        self,
        dataset_code: str,
        geo: Optional[str] = None,
        since: Optional[str] = None,
        filters: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Fetch a Eurostat dataset by its raw dataset code, with optional dimension filters.

        Use this for any Eurostat dataset not covered by `get_indicator`. Dataset
        codes and their dimension names/values can be found via the Eurostat data
        browser at https://ec.europa.eu/eurostat/databrowser.

        Args:
            dataset_code (str): Eurostat dataset code, e.g. "nama_10_gdp", "une_rt_m".
            geo (Optional[str]): Eurostat geo code, e.g. "DE", "FR", "EU27_2020".
            since (Optional[str]): Only return observations from this period
                onward, e.g. "2020" or "2024-01".
            filters (Optional[Dict[str, str]]): Any other dimension filters as
                code/value pairs, e.g. {"sex": "T", "unit": "PC_ACT"}. Values
                must match the dataset's own dimension codes, not free text.

        Returns:
            Dict[str, Any]: Title, source and a list of {..., "value"} records, or an error.
        """
        log_info(f"Fetching Eurostat dataset '{dataset_code}' (geo={geo}, since={since}, filters={filters})")
        params = self._build_params(geo, since, filters)
        try:
            data = self._request(dataset_code, params)
            return self._parse_jsonstat(data)
        except httpx.HTTPStatusError as e:
            return self._http_error(e)
        except Exception as e:
            logger.exception(f"Error fetching Eurostat dataset '{dataset_code}'")
            return {"error": str(e)}

    async def aget_dataset(
        self,
        dataset_code: str,
        geo: Optional[str] = None,
        since: Optional[str] = None,
        filters: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Fetch a Eurostat dataset by its raw dataset code, with optional dimension filters (async).

        Use this for any Eurostat dataset not covered by `get_indicator`. Dataset
        codes and their dimension names/values can be found via the Eurostat data
        browser at https://ec.europa.eu/eurostat/databrowser.

        Args:
            dataset_code (str): Eurostat dataset code, e.g. "nama_10_gdp", "une_rt_m".
            geo (Optional[str]): Eurostat geo code, e.g. "DE", "FR", "EU27_2020".
            since (Optional[str]): Only return observations from this period
                onward, e.g. "2020" or "2024-01".
            filters (Optional[Dict[str, str]]): Any other dimension filters as
                code/value pairs, e.g. {"sex": "T", "unit": "PC_ACT"}. Values
                must match the dataset's own dimension codes, not free text.

        Returns:
            Dict[str, Any]: Title, source and a list of {..., "value"} records, or an error.
        """
        log_info(f"Fetching Eurostat dataset '{dataset_code}' (geo={geo}, since={since}, filters={filters})")
        params = self._build_params(geo, since, filters)
        try:
            data = await self._arequest(dataset_code, params)
            return self._parse_jsonstat(data)
        except httpx.HTTPStatusError as e:
            return self._http_error(e)
        except Exception as e:
            logger.exception(f"Error fetching Eurostat dataset '{dataset_code}'")
            return {"error": str(e)}
