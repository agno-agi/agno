"""EVM integration tools for interacting with EVM Blockchains."""

from os import getenv

from web3 import Web3

from agno.tools import Toolkit
from agno.utils.log import logger


class EvmTools(Toolkit):
    def __init__(
        self,
        private_key: str,
        rpc_url: str,
    ):
        """Initialise EVM tools."""

        super().__init__(name="evm_tools")

        self.private_key = private_key or getenv("EVM_PRIVATE_KEY")
        self.rpc_url = rpc_url or getenv("EVM_RPC_URL")

        if not self.private_key:
            logger.error("Private Key is required")
            raise ValueError("Private Key is required")
        if not self.rpc_url:
            logger.error("RPC Url is needed to interact with EVM blockchain")
            raise ValueError("RPC Url is needed to interact with EVM blockchain")
        if not self.private_key.startswith("0x"):
            self.private_key = f"0x{self.private_key}"
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        self.account = self.w3.eth.account.from_key(self.private_key)
        logger.info(f"Your wallet address is: {self.account.address} ")

    def get_max_priority_fee_per_gas(self) -> int:
        """Get the max priority fee per gas for the transaction.
        Returns:
            int : The max priority fee per gas for the transaction
        """
        max_priority_fee_per_gas = self.w3.to_wei(1, "gwei")
        return max_priority_fee_per_gas

    def get_max_fee_per_gas(self, max_priority_fee_per_gas: int) -> int:
        """Get the max fee per gas for the transaction.
        Args:
            max_priority_fee_per_gas : The max priority fee per gas
        Returns:
            int : The max fee per gas for the transaction
        """
        latest_block = self.w3.eth.get_block("latest")
        base_fee_per_gas = latest_block.get("baseFeePerGas")
        if base_fee_per_gas is None:
            logger.error("Base fee per gas not found in the latest block.")
            raise ValueError("Base fee per gas not found in the latest block.")
        max_fee_per_gas = (5 * base_fee_per_gas) + max_priority_fee_per_gas
        return max_fee_per_gas

    def send_transaction(self, to_address: str, amount_in_wei: int) -> str:
        try:
            """Sends a transaction to the address provided
                Args:
                    to_address : The address to which you want to send eth
                    amount_in_wei : The amount of eth to send in wei
                Returns:
                    str : The transaction hash of the transaction or error message

            """
            max_priority_fee_per_gas = self.get_max_priority_fee_per_gas()
            max_fee_per_gas = self.get_max_fee_per_gas(max_priority_fee_per_gas)
            transaction_params = {
                "from": self.account.address,
                "to": to_address,
                "value": amount_in_wei,
                "nonce": self.w3.eth.get_transaction_count(self.account.address),
                "gas": 21000,
                "maxFeePerGas": max_fee_per_gas,
                "maxPriorityFeePerGas": max_priority_fee_per_gas,
                "chainId": self.w3.eth.chain_id,
            }

            transaction = self.w3.eth.account.sign_transaction(transaction_params, self.private_key)
            transaction_hash = self.w3.eth.send_raw_transaction(transaction.raw_transaction)
            logger.info(f"Ongoing Transaction hash: 0x{transaction_hash.hex()}")
            transaction_receipt = self.w3.eth.wait_for_transaction_receipt(transaction_hash)
            print(transaction_receipt)
            if transaction_receipt.get("status") == 1:
                logger.info(f"Transaction successful! Transaction hash: 0x{transaction_hash.hex()}")
                return f"0x{transaction_hash.hex()}"
            else:
                logger.error("Transaction failed!")
                raise Exception("Transaction failed!")

        except Exception as e:
            logger.error(f"Error sending transaction: {e}")
            return f"error: {e}"
