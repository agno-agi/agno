from typing import Any, Dict

import httpx

from agno.utils.log import log_warning


def get_location() -> Dict[str, Any]:
    """Get approximate location using IP geolocation."""
    try:
        response = httpx.get("https://api.ipify.org?format=json", timeout=5)
        ip = response.json()["ip"]
        response = httpx.get(f"http://ip-api.com/json/{ip}", timeout=5)
        if response.status_code == 200:
            data = response.json()
            return {"city": data.get("city"), "region": data.get("region"), "country": data.get("country")}
    except Exception as e:
        # Location is decoration on the system message, so no lookup failure --
        # network, malformed payload, or anything the client raises -- may
        # escape into the run that is building that message.
        log_warning(f"Failed to get location: {str(e)}")
    return {}
