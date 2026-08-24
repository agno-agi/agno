from typing import Any

import httpx

from agno.utils.log import log_warning


def get_location() -> dict[str, Any]:
    """Get approximate location using IP geolocation."""
    try:
        response = httpx.get("https://api.ipify.org?format=json", timeout=5)
        ip = response.json()["ip"]
        response = httpx.get(f"http://ip-api.com/json/{ip}", timeout=5)
        if response.status_code == 200:
            data = response.json()
            return {"city": data.get("city"), "region": data.get("region"), "country": data.get("country")}
    except (httpx.HTTPError, KeyError, ValueError) as e:
        log_warning(f"Failed to get location: {e!s}")
    return {}
