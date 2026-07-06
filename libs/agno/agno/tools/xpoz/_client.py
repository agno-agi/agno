from os import getenv
from typing import Optional

from agno.utils.log import log_error

try:
    from xpoz import XpozClient
except ImportError:
    raise ImportError("`xpoz` not installed. Please install using `pip install xpoz`")


def get_client(api_key: Optional[str] = None, client: Optional[XpozClient] = None) -> XpozClient:
    if client is not None:
        return client
    resolved_key = api_key or getenv("XPOZ_API_KEY")
    if not resolved_key:
        log_error("XPOZ_API_KEY not provided")
    return XpozClient(api_key=resolved_key, check_update=False, _user_agent="xpoz-agno")
