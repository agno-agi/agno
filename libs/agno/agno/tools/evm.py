from os import getenv
from typing import Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error

try:
    from eth_account.account import LocalAccount
    from eth_account.datastructures import SignedTransaction
    from hexbytes import HexBytes
    from web3 import Web3
    from web3.main import Web3 as Web3Type
    from web3.providers.rpc import HTTPProvider
    from web3.types import TxParams, TxReceipt
except ImportError:
    raise ImportError("`web3` not installed. Please install using `pip install web3`")


class EvmTools(Toolkit):
    def __init__(
        self,
        private_key: Optional[str] = None,
        rpc_url: Optional[str] = None,
        **kwargs,
    ):
        """Initialize EVM tools for blockchain interactions.

        Args:
            private_key: Private key for signing transactions (defaults to EVM_PRIVATE_KEY env var)
            rpc_url: RPC URL for blockchain connection (defaults to EVM_RPC_URL env var)
            **kwargs: Additional arguments passed to parent Toolkit class
        """

        self.private_key = private_key or getenv("EVM_PRIVATE_KEY")
        self.rpc_url = rpc_url or getenv("EVM_RPC_URL")

        if not self.private_key:
            log_error("Private Key is required")
            raise ValueError("Private Key is required")
        if not self.rpc_url:
            log_error("RPC Url is needed to interact with EVM blockchain")
            raise ValueError("RPC Url is needed to interact with EVM blockchain")

        # Ensure private key has 0x prefix
        if not self.private_key.startswith("0x"):
            self.private_key = f"0x{self.private_key}"

        # Initialize Web3 client and account
        self.web3_client: "Web3Type" = Web3(HTTPProvider(self.rpc_url))
        self.account: "LocalAccount" = self.web3_client.eth.account.from_key(self.private_key)
        log_debug(f"Your wallet address is: {self.account.address}")

        super().__init__(name="evm_tools", tools=[self.send_transaction], **kwargs)

    def get_max_priority_fee_per_gas(self) -> int:
        """Get the max priority fee per gas for the transaction.

        Returns:
            int: The max priority fee per gas for the transaction (1 gwei)
        """
        max_priority_fee_per_gas = self.web3_client.to_wei(1, "gwei")
        return max_priority_fee_per_gas

    def get_max_fee_per_gas(self, max_priority_fee_per_gas: int) -> int:
        """Get the max fee per gas for the transaction.

        Args:
            max_priority_fee_per_gas: The max priority fee per gas

        Returns:
            int: The max fee per gas for the transaction
        """
        latest_block = self.web3_client.eth.get_block("latest")
        base_fee_per_gas = latest_block.get("baseFeePerGas")
        if base_fee_per_gas is None:
            log_error("Base fee per gas not found in the latest block.")
            raise ValueError("Base fee per gas not found in the latest block.")
        max_fee_per_gas = (2 * base_fee_per_gas) + max_priority_fee_per_gas
        return max_fee_per_gas

    def send_transaction(self, to_address: str, amount_in_wei: int) -> str:
        """Sends a transaction to the address provided.

        Args:
            to_address: The address to which you want to send ETH
            amount_in_wei: The amount of ETH to send in wei

        Returns:
            str: The transaction hash of the transaction or error message
        """
        try:
            max_priority_fee_per_gas = self.get_max_priority_fee_per_gas()
            max_fee_per_gas = self.get_max_fee_per_gas(max_priority_fee_per_gas)

            transaction_params: "TxParams" = {
                "from": self.account.address,
                "to": to_address,
                "value": amount_in_wei,  # type: ignore[typeddict-item]
                "nonce": self.web3_client.eth.get_transaction_count(self.account.address),
                "gas": 21000,
                "maxFeePerGas": max_fee_per_gas,  # type: ignore[typeddict-item]
                "maxPriorityFeePerGas": max_priority_fee_per_gas,  # type: ignore[typeddict-item]
                "chainId": self.web3_client.eth.chain_id,
                "type": 2,  # EIP-1559 dynamic fee transaction
            }

            signed_transaction: "SignedTransaction" = self.web3_client.eth.account.sign_transaction(
                transaction_params, self.private_key
            )
            transaction_hash: "HexBytes" = self.web3_client.eth.send_raw_transaction(signed_transaction.raw_transaction)
            log_debug(f"Ongoing Transaction hash: 0x{transaction_hash.hex()}")

            transaction_receipt: "TxReceipt" = self.web3_client.eth.wait_for_transaction_receipt(transaction_hash)
            if transaction_receipt.get("status") == 1:
                log_debug(f"Transaction successful! Transaction hash: 0x{transaction_hash.hex()}")
                return f"0x{transaction_hash.hex()}"
            else:
                log_error("Transaction failed!")
                raise Exception("Transaction failed!")

        except Exception as e:
            log_error(f"Error sending transaction: {e}")
            return f"error: {e}"
