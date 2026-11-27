from typing import Any, List
from urllib.parse import quote

import httpx

from agno.tools import Toolkit


class IndianPostalTools(Toolkit):
    """Look up Indian post offices using the Postal PIN Code API."""

    def __init__(
        self, search_by_pincode: bool = True, search_by_postoffice: bool = True, timeout: float = 10.0, **kwargs
    ):
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        self.timeout = timeout
        tools: List[Any] = []
        async_tools: list[tuple[Any, str]] = []
        if search_by_pincode:
            tools.append(self.get_post_offices_by_pincode)
            async_tools.append((self.aget_post_offices_by_pincode, "get_post_offices_by_pincode"))
        if search_by_postoffice:
            tools.append(self.get_post_offices_by_name)
            async_tools.append((self.aget_post_offices_by_name, "get_post_offices_by_name"))
        super().__init__(name="indian_postal_tools", tools=tools, async_tools=async_tools, **kwargs)

    @staticmethod
    def _format_response(data: Any, query: str, by_name: bool) -> str:
        not_found = (
            f"No post offices found matching: '{query}'" if by_name else f"No post offices found for PIN code: {query}"
        )
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
            return "Error: Unexpected response from postal API."
        result = data[0]
        if result.get("Status") == "Error":
            return not_found
        if result.get("Status") != "Success":
            return "Error: Unexpected response from postal API."
        offices = result.get("PostOffice")
        if offices == []:
            return not_found
        if not isinstance(offices, list) or any(not isinstance(office, dict) for office in offices):
            return "Error: Unexpected response from postal API."
        message = result.get("Message")
        lines = [message if isinstance(message, str) else "", ""]
        fields = [("Name", "Name")]
        if by_name:
            fields.append(("PIN Code", "Pincode"))
        fields.extend(
            [
                ("Branch Type", "BranchType"),
                ("Delivery", "DeliveryStatus"),
                ("District", "District"),
                ("Division", "Division"),
                ("Region", "Region"),
                ("State", "State"),
                ("Circle", "Circle"),
                ("Country", "Country"),
            ]
        )
        for office in offices:
            for label, key in fields:
                value = office.get(key)
                lines.append(f"{label:<15}: {value if isinstance(value, str) and value else 'N/A'}")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _valid_pincode(pincode: object) -> bool:
        return (
            isinstance(pincode, str)
            and len(pincode.strip()) == 6
            and pincode.strip().isascii()
            and pincode.strip().isdecimal()
        )

    def _lookup(self, path: str, query: str, by_name: bool) -> str:
        try:
            response = httpx.get(f"https://api.postalpincode.in/{path}/{quote(query, safe='')}", timeout=self.timeout)
            response.raise_for_status()
            return self._format_response(response.json(), query, by_name)
        except httpx.TimeoutException:
            return "Error: Postal API request timed out."
        except httpx.HTTPError:
            return "Error: Could not reach postal API."
        except ValueError:
            return "Error: Unexpected response from postal API."

    async def _alookup(self, path: str, query: str, by_name: bool) -> str:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"https://api.postalpincode.in/{path}/{quote(query, safe='')}")
                response.raise_for_status()
                return self._format_response(response.json(), query, by_name)
        except httpx.TimeoutException:
            return "Error: Postal API request timed out."
        except httpx.HTTPError:
            return "Error: Could not reach postal API."
        except ValueError:
            return "Error: Unexpected response from postal API."

    def get_post_offices_by_pincode(self, pincode: str) -> str:
        """Get post offices for a six-digit Indian PIN code."""
        if not self._valid_pincode(pincode):
            return "Error: PIN code must be exactly 6 digits (e.g., '110001')."
        return self._lookup("pincode", pincode.strip(), False)

    async def aget_post_offices_by_pincode(self, pincode: str) -> str:
        """Get post offices for a six-digit Indian PIN code asynchronously."""
        if not self._valid_pincode(pincode):
            return "Error: PIN code must be exactly 6 digits (e.g., '110001')."
        return await self._alookup("pincode", pincode.strip(), False)

    def get_post_offices_by_name(self, branch_name: str) -> str:
        """Search post offices by full or partial branch name."""
        if not isinstance(branch_name, str) or not branch_name.strip():
            return "Error: Branch name cannot be empty."
        return self._lookup("postoffice", branch_name.strip(), True)

    async def aget_post_offices_by_name(self, branch_name: str) -> str:
        """Search post offices by name asynchronously."""
        if not isinstance(branch_name, str) or not branch_name.strip():
            return "Error: Branch name cannot be empty."
        return await self._alookup("postoffice", branch_name.strip(), True)
