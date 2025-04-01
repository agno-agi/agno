"""EVM integration tools for interacting with EVM Blockchains."""
from os import getenv
from typing import Optional
from web3 import Web3

from agno.tools import Toolkit
from agno.utils.log import logger

class EvmTools(Toolkit):
    def __init__(
        self,
        private_key: str = None,
        rpc_url: str = None,
    ):
        """Initialise EVM tools."""

        super().__init__(name="evm_tools")

        self.private_key = private_key or getenv("EVM_PRIVATE_KEY")
        self.rpc_url = rpc_url or getenv("EVM_RPC_URL")

        if not self.private_key :
            logger.error(f"Private Key is required")
            raise ValueError(f"Private Key is required")
        if not self.rpc_url :
            logger.error(f"RPC Url is needed to interact with EVM blockchain")
            raise ValueError(f"RPC Url is needed to interact with EVM blockchain")
        if not self.private_key.startswith('0x'):
            self.private_key = f"0x{self.private_key}"
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        self.account = self.w3.eth.account.from_key(self.private_key)
        logger.info(f"Your wallet address is: {self.account.address} ")

    def get_priority_fee_per_gas(self) -> int:
        max_priority_fee_per_gas = self.w3.to_wei(1, 'gwei')
        return max_priority_fee_per_gas

    def get_max_fee_per_gas(self,  max_priority_fee_per_gas: str) -> int:
        latest_block = self.w3.eth.get_block("latest")
        base_fee_per_gas = latest_block.baseFeePerGas
        max_fee_per_gas = (5 * base_fee_per_gas) + max_priority_fee_per_gas
        return max_fee_per_gas

    def send_transaction(self, to_address: str, amount_in_wei: int) -> str:
        try:
            '''Sends a transaction to the address provided'''
            max_priority_fee_per_gas = self.get_priority_fee_per_gas()
            max_fee_per_gas = self.get_max_fee_per_gas(max_priority_fee_per_gas)
            transaction_params = {
                'from' : self.account.address,
                'to' : to_address,
                'value': amount_in_wei,
                'nonce': self.w3.eth.get_transaction_count(self.account.address),
                'gas': 21000,
                'maxFeePerGas': max_fee_per_gas,
                'maxPriorityFeePerGas': max_priority_fee_per_gas,
                'chainId': self.w3.eth.chain_id
            }

            transaction = self.w3.eth.account.sign_transaction(transaction_params, self.private_key)
            transaction_hash = self.w3.eth.send_raw_transaction(transaction.rawTransaction)
            logger.info(f"Transaction hash of the trx: {transaction_hash.hex()}")
            transaction_receipt = self.w3.eth.wait_for_transaction_receipt(transaction_hash)

            if transaction_receipt.status:
                return transaction_hash.hex()
            else:
                raise  Exception("Transaction failed!")

        except Exception as e:
            logger.error(f"Error sending transaction: {e}")
            return f"error: {e}"


