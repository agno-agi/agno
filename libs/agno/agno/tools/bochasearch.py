import json
from typing import Any, Dict, List, Optional
from os import getenv
from agno.tools import Toolkit
from agno.utils.log import log_info, logger
import requests


class BoChaSearchTools(Toolkit):
    """
    BoChaSearch is a toolkit for searching BoCha easily.

    Args:
        fixed_max_results (Optional[int]): A fixed number of maximum results.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        fixed_max_results: Optional[int] = None,
        enable_bocha_search: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.fixed_max_results = fixed_max_results
        self.api_key = api_key or getenv("BOCHA_API_KEY")
        if not self.api_key:
            logger.warning("No BoCha API key provided")

        tools = []
        if all or enable_bocha_search:
            tools.append(self.bocha_search)

        super().__init__(name="bochasearch", tools=tools, **kwargs)

    def bocha_search(self, query: str, count: int = 10) -> str:
        """Execute BoCha search and return results

        Args:
            query (str): Search keyword
            count (int, optional): Maximum number of results to return, default 10

        Returns:
            str: A JSON formatted string containing the search results.
        """
        max_results = self.fixed_max_results or count
        url = 'https://api.bochaai.com/v1/web-search'
        headers = {
            'Authorization': f'Bearer {self.api_key}',  # 请替换为你的API密钥
            'Content-Type': 'application/json'
        }
        data = {
            "query": query,
            "freshness": "noLimit",  # 搜索的时间范围，
            "summary": True,  # 是否返回长文本摘要
            "count": max_results
        }

        response = requests.post(url, headers=headers, json=data)

        json_response = response.json()
        results = json_response["data"]["webPages"]["value"]

        print(json.dumps(results, ensure_ascii=False, indent=2))

        res: List[Dict[str, str]] = []
        for idx, item in enumerate(results, 1):
            res.append(
                {
                    "title": item.get("name", ""),
                    "url": item.get("url", ""),
                    "abstract": item.get("summary", ""),
                    "rank": str(idx),
                }
            )
        return json.dumps(res, indent=2)
