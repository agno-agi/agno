from typing import Any, List, Optional

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_debug


class IndianPostalTools(Toolkit):
    """
    IndianPostalTools is a toolkit for querying Indian Post Offices using
    the free Postal PIN Code API. No API key is required.

    Source: https://www.postalpincode.in

    Args:
        search_by_pincode (bool): Enable searching post offices by 6-digit PIN code.
        search_by_postoffice (bool): Enable searching post offices by branch name.
    """

    def __init__(
        self,
        search_by_pincode: bool = True,
        search_by_postoffice: bool = True,
        **kwargs,
    ):
        tools: List[Any] = []

        if search_by_pincode:
            tools.append(self.get_post_offices_by_pincode)
        if search_by_postoffice:
            tools.append(self.get_post_offices_by_name)

        super().__init__(name="indian_postal_tools", tools=tools, **kwargs)

    def get_post_offices_by_pincode(self, pincode: str) -> str:
        """
        Get details of Post Office(s) by Indian 6-digit postal PIN code.

        Args:
            pincode: A 6-digit Indian postal PIN code (e.g., '110001' for New Delhi).

        Returns:
            Formatted string listing all post offices for the PIN code, or an error message.
        """
        pincode = pincode.strip()
        if not pincode.isdigit() or len(pincode) != 6:
            return "Error: PIN code must be exactly 6 digits (e.g., '110001')."

        url = f"https://api.postalpincode.in/pincode/{pincode}"
        log_debug(f"Fetching post offices for PIN code: {pincode}")

        try:
            response = httpx.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            result = data[0]

            if result.get("Status") == "Error":
                return f"No post offices found for PIN code: {pincode}"

            post_offices: Optional[List[Any]] = result.get("PostOffice")
            if not post_offices:
                return f"No post offices found for PIN code: {pincode}"

            output_lines: List[str] = [result.get("Message", ""), ""]
            for po in post_offices:
                output_lines.extend(
                    [
                        f"Name           : {po.get('Name', 'N/A')}",
                        f"Branch Type    : {po.get('BranchType', 'N/A')}",
                        f"Delivery       : {po.get('DeliveryStatus', 'N/A')}",
                        f"District       : {po.get('District', 'N/A')}",
                        f"Division       : {po.get('Division', 'N/A')}",
                        f"Region         : {po.get('Region', 'N/A')}",
                        f"State          : {po.get('State', 'N/A')}",
                        f"Circle         : {po.get('Circle', 'N/A')}",
                        f"Country        : {po.get('Country', 'N/A')}",
                        "",
                    ]
                )
            return "\n".join(output_lines)

        except httpx.HTTPError as e:
            return f"Error: Could not reach postal API. Details: {e}"
        except Exception as e:
            return f"Error: {e}"

    def get_post_offices_by_name(self, branch_name: str) -> str:
        """
        Search Indian Post Office(s) by branch name.

        Args:
            branch_name: Full or partial name of a post office branch (e.g., 'Bandra' or 'Connaught Place').

        Returns:
            Formatted string listing matching post offices with their PIN codes, or an error message.
        """
        branch_name = branch_name.strip()
        if not branch_name:
            return "Error: Branch name cannot be empty."

        url = f"https://api.postalpincode.in/postoffice/{branch_name}"
        log_debug(f"Searching post offices by name: {branch_name}")

        try:
            response = httpx.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            result = data[0]

            if result.get("Status") == "Error":
                return f"No post offices found matching: '{branch_name}'"

            post_offices: Optional[List[Any]] = result.get("PostOffice")
            if not post_offices:
                return f"No post offices found matching: '{branch_name}'"

            output_lines: List[str] = [result.get("Message", ""), ""]
            for po in post_offices:
                output_lines.extend(
                    [
                        f"Name           : {po.get('Name', 'N/A')}",
                        f"PIN Code       : {po.get('Pincode', 'N/A')}",
                        f"Branch Type    : {po.get('BranchType', 'N/A')}",
                        f"Delivery       : {po.get('DeliveryStatus', 'N/A')}",
                        f"District       : {po.get('District', 'N/A')}",
                        f"Division       : {po.get('Division', 'N/A')}",
                        f"Region         : {po.get('Region', 'N/A')}",
                        f"State          : {po.get('State', 'N/A')}",
                        f"Circle         : {po.get('Circle', 'N/A')}",
                        f"Country        : {po.get('Country', 'N/A')}",
                        "",
                    ]
                )
            return "\n".join(output_lines)

        except httpx.HTTPError as e:
            return f"Error: Could not reach postal API. Details: {e}"
        except Exception as e:
            return f"Error: {e}"
