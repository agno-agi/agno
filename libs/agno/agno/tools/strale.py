import json
from os import getenv
from typing import Any, List, Optional

from agno.tools import Toolkit

try:
    from straleio import Strale, DoRequest
except ImportError:
    raise ImportError("`straleio` not installed. Please install using `pip install straleio`")


class StraleTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        enable_validate_iban: bool = True,
        enable_validate_email: bool = True,
        enable_lookup_company: bool = True,
        enable_check_sanctions: bool = True,
        all: bool = False,
        **kwargs,
    ):
        super().__init__(name="strale_tools")

        self.api_key = api_key or getenv("STRALE_API_KEY")
        if not self.api_key:
            raise ValueError(
                "STRALE_API_KEY not set. Please set the STRALE_API_KEY environment variable or pass api_key to StraleTools."
            )

        self.client = Strale(api_key=self.api_key)

        tools: List[Any] = []
        if all or enable_validate_iban:
            tools.append(self.validate_iban)
        if all or enable_validate_email:
            tools.append(self.validate_email)
        if all or enable_lookup_company:
            tools.append(self.lookup_company)
        if all or enable_check_sanctions:
            tools.append(self.check_sanctions)

        super().__init__(name="strale_tools", tools=tools, **kwargs)

    def validate_iban(self, iban: str) -> str:
        """Validate an International Bank Account Number (IBAN) using Strale.
        This is a free tier capability.

        Args:
            iban (str): The IBAN string to validate.

        Returns:
            str: JSON response containing validation results, quality score, and audit details.
        """
        try:
            req = DoRequest(
                capability_slug="iban-validate",
                inputs={"iban": iban},
                max_price_cents=10,
            )
            result = self.client.do(req)
            return json.dumps(result.output, indent=2)
        except Exception as e:
            return f"Error validating IBAN: {e}"

    def validate_email(self, email: str) -> str:
        """Validate an email address structure and deliverability using Strale.
        This is a free tier capability.

        Args:
            email (str): The email address to validate.

        Returns:
            str: JSON response containing validation results, quality score, and audit details.
        """
        try:
            req = DoRequest(
                capability_slug="email-validate",
                inputs={"email": email},
                max_price_cents=10,
            )
            result = self.client.do(req)
            return json.dumps(result.output, indent=2)
        except Exception as e:
            return f"Error validating email: {e}"

    def lookup_company(self, company_name: str, country: Optional[str] = None) -> str:
        """Look up company registry details using Strale.
        This is a paid capability.

        Args:
            company_name (str): The name of the company to look up.
            country (str, optional): The 2-letter country code (ISO 3166-1 alpha-2, e.g., 'US', 'GB') to filter by.

        Returns:
            str: JSON response containing company information and registry status.
        """
        try:
            inputs = {"company_name": company_name}
            if country:
                inputs["country"] = country
            req = DoRequest(
                capability_slug="company-search",
                inputs=inputs,
                max_price_cents=100,
            )
            result = self.client.do(req)
            return json.dumps(result.output, indent=2)
        except Exception as e:
            return f"Error looking up company: {e}"

    def check_sanctions(self, name: str, country: Optional[str] = None) -> str:
        """Perform sanctions screening for a person or organization using Strale.
        This is a paid capability.

        Args:
            name (str): The name of the person or entity to screen.
            country (str, optional): 2-letter country code of the entity.

        Returns:
            str: JSON response containing sanctions screening match results and risk indicators.
        """
        try:
            inputs = {"name": name}
            if country:
                inputs["country"] = country
            req = DoRequest(
                capability_slug="sanctions-screening",
                inputs=inputs,
                max_price_cents=100,
            )
            result = self.client.do(req)
            return json.dumps(result.output, indent=2)
        except Exception as e:
            return f"Error screening sanctions: {e}"
