from typing import Dict, Optional

from agno.databricks.utils import merge_headers

DEFAULT_DATABRICKS_USER_AGENT = "agno-databricks/0.1"


def build_databricks_headers(
    token: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    user_agent: str = DEFAULT_DATABRICKS_USER_AGENT,
) -> Dict[str, str]:
    auth_headers: Dict[str, str] = {"User-Agent": user_agent}
    if token:
        auth_headers["Authorization"] = f"Bearer {token}"

    return merge_headers(auth_headers, headers)
