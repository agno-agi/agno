import json
from typing import TYPE_CHECKING, Any, List, Optional

from agno.tools import Toolkit
from agno.tools.xpoz._client import get_client

if TYPE_CHECKING:
    from xpoz import XpozClient
from agno.utils.log import logger


class XpozAccountTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        client: Optional["XpozClient"] = None,
        enable_get_account_details: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self._client = get_client(api_key, client=client)

        tools: List[Any] = []
        if all or enable_get_account_details:
            tools.append(self.account_get_account_details)

        super().__init__(name="xpoz_account", tools=tools, **kwargs)

    def account_get_account_details(self) -> str:
        """Get Xpoz account details including plan information, billing, and usage statistics.

        Returns:
            str: JSON string with account details (plan, billing, usage).
        """
        try:
            result = self._client.account.get_account_details()
            return json.dumps(result.model_dump())
        except Exception as e:
            logger.exception("Failed to execute account_get_account_details")
            return json.dumps({"error": str(e)})
