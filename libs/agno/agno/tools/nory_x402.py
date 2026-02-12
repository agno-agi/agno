"""Nory x402 Payment Tools for Agno.

Tools for AI agents to make payments using the x402 HTTP protocol.
Supports Solana and 7 EVM chains with sub-400ms settlement.
"""

import json
from typing import Any, Dict, List, Literal, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger

try:
    import requests
except ImportError:
    raise ImportError("`requests` not installed. Please install using `pip install requests`")


NORY_API_BASE = "https://noryx402.com"

NoryNetwork = Literal[
    "solana-mainnet",
    "solana-devnet",
    "base-mainnet",
    "polygon-mainnet",
    "arbitrum-mainnet",
    "optimism-mainnet",
    "avalanche-mainnet",
    "sei-mainnet",
    "iotex-mainnet",
]


class NoryX402Tools(Toolkit):
    """Tools for making payments using the x402 HTTP protocol via Nory.

    Nory provides payment infrastructure for AI agents, supporting Solana and
    7 EVM chains (Base, Polygon, Arbitrum, Optimism, Avalanche, Sei, IoTeX)
    with sub-400ms settlement times.

    Use these tools when encountering HTTP 402 Payment Required responses.

    Args:
        api_key: Nory API key (optional for public endpoints).
        enable_get_payment_requirements: Enable get_payment_requirements tool.
        enable_verify_payment: Enable verify_payment tool.
        enable_settle_payment: Enable settle_payment tool.
        enable_lookup_transaction: Enable lookup_transaction tool.
        enable_health_check: Enable health_check tool.
        all: Enable all tools.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        enable_get_payment_requirements: bool = True,
        enable_verify_payment: bool = True,
        enable_settle_payment: bool = True,
        enable_lookup_transaction: bool = True,
        enable_health_check: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.api_key = api_key

        tools: List[Any] = []
        if all or enable_get_payment_requirements:
            tools.append(self.get_payment_requirements)
        if all or enable_verify_payment:
            tools.append(self.verify_payment)
        if all or enable_settle_payment:
            tools.append(self.settle_payment)
        if all or enable_lookup_transaction:
            tools.append(self.lookup_transaction)
        if all or enable_health_check:
            tools.append(self.health_check)

        super().__init__(name="nory_x402", tools=tools, **kwargs)

    def _get_headers(self, content_type: bool = False) -> Dict[str, str]:
        """Get request headers with optional auth."""
        headers: Dict[str, str] = {}
        if content_type:
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def get_payment_requirements(
        self,
        resource: str,
        amount: str,
        network: Optional[str] = None,
    ) -> str:
        """Get x402 payment requirements for accessing a paid resource.

        Use this when you encounter an HTTP 402 Payment Required response
        and need to know how much to pay and where to send payment.

        Args:
            resource (str): The resource path requiring payment (e.g., /api/premium/data).
            amount (str): Amount in human-readable format (e.g., '0.10' for $0.10 USDC).
            network (Optional[str]): Preferred blockchain network. Options: solana-mainnet,
                solana-devnet, base-mainnet, polygon-mainnet, arbitrum-mainnet,
                optimism-mainnet, avalanche-mainnet, sei-mainnet, iotex-mainnet.

        Returns:
            str: JSON string with payment requirements including amount, supported networks,
                and wallet address.
        """
        try:
            log_debug(f"Getting payment requirements for resource: {resource}")
            params: Dict[str, str] = {"resource": resource, "amount": amount}
            if network:
                params["network"] = network

            response = requests.get(
                f"{NORY_API_BASE}/api/x402/requirements",
                params=params,
                headers=self._get_headers(),
                timeout=30,
            )
            response.raise_for_status()
            return json.dumps(response.json(), indent=2)
        except requests.exceptions.RequestException as e:
            error_message = f"Request failed: {str(e)}"
            logger.error(error_message)
            return json.dumps({"error": error_message}, indent=2)

    def verify_payment(self, payload: str) -> str:
        """Verify a signed payment transaction before settlement.

        Use this to validate that a payment transaction is correct
        before submitting it to the blockchain.

        Args:
            payload (str): Base64-encoded payment payload containing signed transaction.

        Returns:
            str: JSON string with verification result including validity and payer info.
        """
        try:
            log_debug("Verifying payment transaction")
            response = requests.post(
                f"{NORY_API_BASE}/api/x402/verify",
                json={"payload": payload},
                headers=self._get_headers(content_type=True),
                timeout=30,
            )
            response.raise_for_status()
            return json.dumps(response.json(), indent=2)
        except requests.exceptions.RequestException as e:
            error_message = f"Request failed: {str(e)}"
            logger.error(error_message)
            return json.dumps({"error": error_message}, indent=2)

    def settle_payment(self, payload: str) -> str:
        """Settle a payment on-chain with ~400ms settlement time.

        Use this to submit a verified payment transaction to the blockchain.
        Settlement typically completes in under 400ms.

        Args:
            payload (str): Base64-encoded payment payload.

        Returns:
            str: JSON string with settlement result including transaction ID and network.
        """
        try:
            log_debug("Settling payment on-chain")
            response = requests.post(
                f"{NORY_API_BASE}/api/x402/settle",
                json={"payload": payload},
                headers=self._get_headers(content_type=True),
                timeout=30,
            )
            response.raise_for_status()
            return json.dumps(response.json(), indent=2)
        except requests.exceptions.RequestException as e:
            error_message = f"Request failed: {str(e)}"
            logger.error(error_message)
            return json.dumps({"error": error_message}, indent=2)

    def lookup_transaction(self, transaction_id: str, network: str) -> str:
        """Look up transaction status.

        Use this to check the status of a previously submitted payment
        including confirmations and current state.

        Args:
            transaction_id (str): Transaction ID or signature.
            network (str): Network where the transaction was submitted. Options:
                solana-mainnet, solana-devnet, base-mainnet, polygon-mainnet,
                arbitrum-mainnet, optimism-mainnet, avalanche-mainnet,
                sei-mainnet, iotex-mainnet.

        Returns:
            str: JSON string with transaction status (pending, confirmed, failed)
                and confirmations.
        """
        try:
            log_debug(f"Looking up transaction: {transaction_id}")
            response = requests.get(
                f"{NORY_API_BASE}/api/x402/transactions/{transaction_id}",
                params={"network": network},
                headers=self._get_headers(),
                timeout=30,
            )
            response.raise_for_status()
            return json.dumps(response.json(), indent=2)
        except requests.exceptions.RequestException as e:
            error_message = f"Request failed: {str(e)}"
            logger.error(error_message)
            return json.dumps({"error": error_message}, indent=2)

    def health_check(self) -> str:
        """Check Nory service health and see supported networks.

        Use this to verify the payment service is operational
        before attempting payments.

        Returns:
            str: JSON string with health status and list of supported blockchain networks.
        """
        try:
            log_debug("Checking Nory service health")
            response = requests.get(
                f"{NORY_API_BASE}/api/x402/health",
                timeout=30,
            )
            response.raise_for_status()
            return json.dumps(response.json(), indent=2)
        except requests.exceptions.RequestException as e:
            error_message = f"Request failed: {str(e)}"
            logger.error(error_message)
            return json.dumps({"error": error_message}, indent=2)
