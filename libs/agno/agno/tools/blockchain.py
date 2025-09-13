import json
from os import getenv
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_info, logger

try:
    from web3 import Web3
    from web3.exceptions import ContractLogicError
    from eth_account import Account
    import requests
except ImportError:
    raise ImportError("`web3` not installed. Please install using `pip install web3 requests`")

# Define blockchain network mappings
NETWORK_CHAIN_IDS = {
    "ethereum": 1,
    "ropsten": 3,
    "rinkeby": 4,
    "goerli": 5,
    "kovan": 42,
    "polygon": 137,
    "mumbai": 80001,
    "binance": 56,
    "bsc-testnet": 97,
    "avalanche": 43114,
    "fuji": 43113,
    "fantom": 250,
    "cronos": 25,
    "arbitrum": 42161,
    "optimism": 10,
}

# Define RPC endpoints for common networks
NETWORK_RPC_ENDPOINTS = {
    "ethereum": "https://mainnet.infura.io/v3/",
    "polygon": "https://polygon-rpc.com/",
    "binance": "https://bsc-dataseed.binance.org/",
    "avalanche": "https://api.avax.network/ext/bc/C/rpc",
    "fantom": "https://rpc.ftm.tools/",
    "cronos": "https://evm.cronos.org/",
    "arbitrum": "https://arb1.arbitrum.io/rpc",
    "optimism": "https://mainnet.optimism.io",
}

# ERC20 ABI for token interactions
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "name",
        "outputs": [{"name": "", "type": "string"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [{"name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [{"name": "to", "type": "address"}, {"name": "value", "type": "uint256"}],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function"
    }
]


class BlockchainTools(Toolkit):
    """A comprehensive toolkit for interacting with various blockchain networks.
    
    Supports Ethereum and EVM-compatible blockchains with functions for:
    - Reading wallet balances
    - Sending transactions
    - Reading token balances
    - Getting network statistics
    - Viewing transaction details
    
    Supported networks include:
    - ethereum (mainnet)
    - ropsten, rinkeby, goerli, kovan (Ethereum testnets)
    - polygon, mumbai (Polygon/Matic)
    - binance, bsc-testnet (Binance Smart Chain)
    - avalanche, fuji (Avalanche)
    - fantom, cronos, arbitrum, optimism
    """

    def __init__(
        self,
        private_key: Optional[str] = None,
        networks: Optional[Dict[str, str]] = None,
        default_network: str = "ethereum",
        infura_project_id: Optional[str] = None,
        alchemy_api_key: Optional[str] = None,
        **kwargs
    ):
        """Initialize the BlockchainTools.
        
        Args:
            private_key: Private key for signing transactions (defaults to BLOCKCHAIN_PRIVATE_KEY env var)
            networks: Dictionary mapping network names to RPC URLs
            default_network: Default network to use for operations. 
                           Supported: ethereum, ropsten, rinkeby, goerli, kovan, 
                           polygon, mumbai, binance, bsc-testnet, avalanche, fuji,
                           fantom, cronos, arbitrum, optimism
            infura_project_id: Infura Project ID for Ethereum connections
            alchemy_api_key: Alchemy API key for enhanced functionality
        """
        self.private_key = private_key or getenv("BLOCKCHAIN_PRIVATE_KEY")
        self.infura_project_id = infura_project_id or getenv("INFURA_PROJECT_ID")
        self.alchemy_api_key = alchemy_api_key or getenv("ALCHEMY_API_KEY")
        self.default_network = default_network
        
        # Initialize networks configuration
        self.networks = networks or {}
        
        # Add default RPC endpoints if not provided
        for network_name, rpc_url in NETWORK_RPC_ENDPOINTS.items():
            if network_name not in self.networks:
                # For Infura-supported networks, use Infura if project ID is provided
                if network_name == "ethereum" and self.infura_project_id:
                    self.networks[network_name] = f"{rpc_url}{self.infura_project_id}"
                else:
                    self.networks[network_name] = rpc_url
                    
        # Initialize Web3 clients for each network
        self.clients: Dict[str, Web3] = {}
        self.accounts: Dict[str, Account] = {}
        
        if self.private_key:
            # Ensure private key has 0x prefix
            if not self.private_key.startswith("0x"):
                self.private_key = f"0x{self.private_key}"
                
            # Initialize clients and accounts
            for network_name, rpc_url in self.networks.items():
                try:
                    self.clients[network_name] = Web3(Web3.HTTPProvider(rpc_url))
                    self.accounts[network_name] = Account.from_key(self.private_key)
                    log_debug(f"Initialized {network_name} client with account {self.accounts[network_name].address}")
                except Exception as e:
                    log_error(f"Failed to initialize {network_name} client: {e}")
        
        # Register tools
        tools = []
        tools.append(self.get_wallet_balance)
        tools.append(self.get_token_balance)
        tools.append(self.get_network_stats)
        tools.append(self.get_transaction_details)
        tools.append(self.get_block_details)
        tools.append(self.send_crypto)
        tools.append(self.deploy_contract)
        tools.append(self.interact_with_contract)
        tools.append(self.get_gas_price)
        tools.append(self.estimate_gas)
        tools.append(self.get_contract_abi)
        
        super().__init__(name="blockchain_tools", tools=tools, **kwargs)

    def _get_client(self, network: Optional[str] = None) -> Web3:
        """Get Web3 client for specified network or default network."""
        network = network or self.default_network
        if network not in self.clients:
            raise ValueError(f"Network {network} not configured")
        return self.clients[network]
    
    def _get_account(self, network: Optional[str] = None) -> Optional[Account]:
        """Get account for specified network or default network."""
        network = network or self.default_network
        return self.accounts.get(network)
    
    def _get_network_chain_id(self, network: Optional[str] = None) -> int:
        """Get chain ID for specified network."""
        network = network or self.default_network
        return NETWORK_CHAIN_IDS.get(network, 0)

    def get_wallet_balance(self, wallet_address: str, network: Optional[str] = None) -> str:
        """Get the balance of a wallet on a specific blockchain network.
        
        Args:
            wallet_address: Wallet address to check balance for
            network: Blockchain network. Supported networks: ethereum, ropsten, rinkeby, 
                   goerli, kovan, polygon, mumbai, binance, bsc-testnet, avalanche, fuji,
                   fantom, cronos, arbitrum, optimism. Defaults to ethereum.
            
        Returns:
            JSON string with balance information
        """
        try:
            client = self._get_client(network)
            network = network or self.default_network
            
            # Validate wallet address
            if not client.is_address(wallet_address):
                return json.dumps({"error": f"Invalid wallet address: {wallet_address}"})
            
            checksum_address = client.to_checksum_address(wallet_address)
            balance_wei = client.eth.get_balance(checksum_address)
            balance_eth = client.from_wei(balance_wei, 'ether')
            
            result = {
                "wallet_address": wallet_address,
                "network": network,
                "balance_wei": str(balance_wei),
                "balance_native_token": float(balance_eth),
                "chain_id": self._get_network_chain_id(network)
            }
            
            log_info(f"Balance for {wallet_address} on {network}: {balance_eth}")
            return json.dumps(result)
            
        except Exception as e:
            error_msg = f"Error getting wallet balance: {str(e)}"
            log_error(error_msg)
            return json.dumps({"error": error_msg})

    def get_token_balance(self, wallet_address: str, token_address: str, network: Optional[str] = None) -> str:
        """Get the ERC20 token balance of a wallet.
        
        Args:
            wallet_address: Wallet address to check balance for
            token_address: Contract address of the ERC20 token
            network: Blockchain network. Supported networks: ethereum, ropsten, rinkeby, 
                   goerli, kovan, polygon, mumbai, binance, bsc-testnet, avalanche, fuji,
                   fantom, cronos, arbitrum, optimism. Defaults to ethereum.
            
        Returns:
            JSON string with token balance information
        """
        try:
            client = self._get_client(network)
            network = network or self.default_network
            
            # Validate addresses
            if not client.is_address(wallet_address):
                return json.dumps({"error": f"Invalid wallet address: {wallet_address}"})
            
            if not client.is_address(token_address):
                return json.dumps({"error": f"Invalid token address: {token_address}"})
            
            checksum_wallet = client.to_checksum_address(wallet_address)
            checksum_token = client.to_checksum_address(token_address)
            
            # Create contract instance
            token_contract = client.eth.contract(address=checksum_token, abi=ERC20_ABI)
            
            # Get token info
            token_name = token_contract.functions.name().call()
            token_symbol = token_contract.functions.symbol().call()
            token_decimals = token_contract.functions.decimals().call()
            
            # Get balance
            balance = token_contract.functions.balanceOf(checksum_wallet).call()
            adjusted_balance = balance / (10 ** token_decimals)
            
            result = {
                "wallet_address": wallet_address,
                "token_address": token_address,
                "token_name": token_name,
                "token_symbol": token_symbol,
                "balance_raw": str(balance),
                "balance_adjusted": float(adjusted_balance),
                "decimals": token_decimals,
                "network": network
            }
            
            log_info(f"Token balance for {wallet_address}: {adjusted_balance} {token_symbol}")
            return json.dumps(result)
            
        except Exception as e:
            error_msg = f"Error getting token balance: {str(e)}"
            log_error(error_msg)
            return json.dumps({"error": error_msg})

    def get_network_stats(self, network: Optional[str] = None) -> str:
        """Get current statistics for a blockchain network.
        
        Args:
            network: Blockchain network. Supported networks: ethereum, ropsten, rinkeby, 
                   goerli, kovan, polygon, mumbai, binance, bsc-testnet, avalanche, fuji,
                   fantom, cronos, arbitrum, optimism. Defaults to ethereum.
            
        Returns:
            JSON string with network statistics
        """
        try:
            client = self._get_client(network)
            network = network or self.default_network
            
            # Get latest block
            latest_block = client.eth.get_block('latest')
            block_number = latest_block.number
            timestamp = latest_block.timestamp
            
            # Get gas price
            gas_price_wei = client.eth.gas_price
            gas_price_gwei = client.from_wei(gas_price_wei, 'gwei')
            
            # Get network ID
            network_id = client.net.version
            
            result = {
                "network": network,
                "latest_block": block_number,
                "block_timestamp": timestamp,
                "gas_price_wei": str(gas_price_wei),
                "gas_price_gwei": float(gas_price_gwei),
                "network_id": network_id,
                "chain_id": self._get_network_chain_id(network)
            }
            
            log_info(f"Network stats for {network}: Block {block_number}, Gas {gas_price_gwei} Gwei")
            return json.dumps(result)
            
        except Exception as e:
            error_msg = f"Error getting network stats: {str(e)}"
            log_error(error_msg)
            return json.dumps({"error": error_msg})

    def get_transaction_details(self, tx_hash: str, network: Optional[str] = None) -> str:
        """Get details of a blockchain transaction.
        
        Args:
            tx_hash: Transaction hash
            network: Blockchain network. Supported networks: ethereum, ropsten, rinkeby, 
                   goerli, kovan, polygon, mumbai, binance, bsc-testnet, avalanche, fuji,
                   fantom, cronos, arbitrum, optimism. Defaults to ethereum.
            
        Returns:
            JSON string with transaction details
        """
        try:
            client = self._get_client(network)
            network = network or self.default_network
            
            # Add 0x prefix if missing
            if not tx_hash.startswith("0x"):
                tx_hash = f"0x{tx_hash}"
            
            # Get transaction
            tx = client.eth.get_transaction(tx_hash)
            receipt = client.eth.get_transaction_receipt(tx_hash)
            
            result = {
                "hash": tx_hash,
                "network": network,
                "from": tx["from"],
                "to": tx["to"],
                "value_wei": str(tx["value"]),
                "value_eth": float(client.from_wei(tx["value"], "ether")),
                "gas_price_wei": str(tx["gasPrice"]),
                "gas_price_gwei": float(client.from_wei(tx["gasPrice"], "gwei")),
                "gas_limit": tx["gas"],
                "nonce": tx["nonce"],
                "block_number": tx["blockNumber"],
                "block_hash": tx["blockHash"].hex(),
                "status": "success" if receipt.status == 1 else "failed",
                "gas_used": str(receipt.gasUsed),
                "cumulative_gas_used": str(receipt.cumulativeGasUsed)
            }
            
            log_info(f"Transaction details for {tx_hash}")
            return json.dumps(result)
            
        except Exception as e:
            error_msg = f"Error getting transaction details: {str(e)}"
            log_error(error_msg)
            return json.dumps({"error": error_msg})

    def get_block_details(self, block_number: Union[int, str] = "latest", network: Optional[str] = None) -> str:
        """Get details of a blockchain block.
        
        Args:
            block_number: Block number or 'latest'
            network: Blockchain network. Supported networks: ethereum, ropsten, rinkeby, 
                   goerli, kovan, polygon, mumbai, binance, bsc-testnet, avalanche, fuji,
                   fantom, cronos, arbitrum, optimism. Defaults to ethereum.
            
        Returns:
            JSON string with block details
        """
        try:
            client = self._get_client(network)
            network = network or self.default_network
            
            # Get block
            block = client.eth.get_block(block_number)
            
            result = {
                "network": network,
                "block_number": block.number,
                "block_hash": block.hash.hex(),
                "parent_hash": block.parentHash.hex(),
                "timestamp": block.timestamp,
                "miner": block.miner,
                "gas_limit": str(block.gasLimit),
                "gas_used": str(block.gasUsed),
                "transactions_count": len(block.transactions),
                "difficulty": str(block.difficulty),
                "size": block.size,
                "nonce": block.nonce.hex()
            }
            
            log_info(f"Block details for block {block.number}")
            return json.dumps(result)
            
        except Exception as e:
            error_msg = f"Error getting block details: {str(e)}"
            log_error(error_msg)
            return json.dumps({"error": error_msg})

    def send_crypto(self, to_address: str, amount_eth: float, network: Optional[str] = None) -> str:
        """Send native cryptocurrency to a wallet address.
        
        Args:
            to_address: Recipient wallet address
            amount_eth: Amount to send in native token (ETH, MATIC, BNB, etc.)
            network: Blockchain network. Supported networks: ethereum, ropsten, rinkeby, 
                   goerli, kovan, polygon, mumbai, binance, bsc-testnet, avalanche, fuji,
                   fantom, cronos, arbitrum, optimism. Defaults to ethereum.
            
        Returns:
            JSON string with transaction details
        """
        try:
            client = self._get_client(network)
            account = self._get_account(network)
            network = network or self.default_network
            
            if not account:
                return json.dumps({"error": "No account configured for signing transactions"})
            
            # Validate recipient address
            if not client.is_address(to_address):
                return json.dumps({"error": f"Invalid recipient address: {to_address}"})
            
            checksum_to = client.to_checksum_address(to_address)
            amount_wei = client.to_wei(amount_eth, 'ether')
            
            # Get nonce
            nonce = client.eth.get_transaction_count(account.address)
            
            # Get gas price
            gas_price = client.eth.gas_price
            
            # Estimate gas
            transaction = {
                'to': checksum_to,
                'value': amount_wei,
                'gas': 21000,
                'gasPrice': gas_price,
                'nonce': nonce,
                'chainId': self._get_network_chain_id(network)
            }
            
            # Sign and send transaction
            signed_txn = client.eth.account.sign_transaction(transaction, self.private_key)
            tx_hash = client.eth.send_raw_transaction(signed_txn.rawTransaction)
            
            result = {
                "from": account.address,
                "to": to_address,
                "amount_wei": str(amount_wei),
                "amount_eth": amount_eth,
                "network": network,
                "transaction_hash": tx_hash.hex(),
                "gas_price_wei": str(gas_price)
            }
            
            log_info(f"Sent {amount_eth} {network} tokens to {to_address}")
            return json.dumps(result)
            
        except Exception as e:
            error_msg = f"Error sending crypto: {str(e)}"
            log_error(error_msg)
            return json.dumps({"error": error_msg})

    def deploy_contract(self, bytecode: str, abi: List[Dict], network: Optional[str] = None) -> str:
        """Deploy a smart contract to the blockchain.
        
        Args:
            bytecode: Compiled contract bytecode
            abi: Contract ABI
            network: Blockchain network. Supported networks: ethereum, ropsten, rinkeby, 
                   goerli, kovan, polygon, mumbai, binance, bsc-testnet, avalanche, fuji,
                   fantom, cronos, arbitrum, optimism. Defaults to ethereum.
            
        Returns:
            JSON string with deployment details
        """
        try:
            client = self._get_client(network)
            account = self._get_account(network)
            network = network or self.default_network
            
            if not account:
                return json.dumps({"error": "No account configured for signing transactions"})
            
            # Create contract instance
            contract = client.eth.contract(abi=abi, bytecode=bytecode)
            
            # Get nonce
            nonce = client.eth.get_transaction_count(account.address)
            
            # Get gas price
            gas_price = client.eth.gas_price
            
            # Deploy contract
            transaction = contract.constructor().build_transaction({
                'from': account.address,
                'nonce': nonce,
                'gasPrice': gas_price,
                'chainId': self._get_network_chain_id(network)
            })
            
            # Estimate gas
            gas_estimate = client.eth.estimate_gas(transaction)
            transaction['gas'] = gas_estimate
            
            # Sign and send transaction
            signed_txn = client.eth.account.sign_transaction(transaction, self.private_key)
            tx_hash = client.eth.send_raw_transaction(signed_txn.rawTransaction)
            
            result = {
                "deployer": account.address,
                "network": network,
                "transaction_hash": tx_hash.hex(),
                "gas_used_estimate": gas_estimate,
                "gas_price_wei": str(gas_price)
            }
            
            log_info(f"Deployed contract with transaction {tx_hash.hex()}")
            return json.dumps(result)
            
        except Exception as e:
            error_msg = f"Error deploying contract: {str(e)}"
            log_error(error_msg)
            return json.dumps({"error": error_msg})

    def interact_with_contract(self, contract_address: str, abi: List[Dict], 
                              function_name: str, function_args: Optional[List] = None,
                              value_eth: float = 0, network: Optional[str] = None) -> str:
        """Interact with a deployed smart contract.
        
        Args:
            contract_address: Address of the deployed contract
            abi: Contract ABI
            function_name: Name of the function to call
            function_args: Arguments for the function call
            value_eth: Value to send with the transaction (in ETH)
            network: Blockchain network. Supported networks: ethereum, ropsten, rinkeby, 
                   goerli, kovan, polygon, mumbai, binance, bsc-testnet, avalanche, fuji,
                   fantom, cronos, arbitrum, optimism. Defaults to ethereum.
            
        Returns:
            JSON string with interaction details
        """
        try:
            client = self._get_client(network)
            account = self._get_account(network)
            network = network or self.default_network
            function_args = function_args or []
            
            if not account:
                return json.dumps({"error": "No account configured for signing transactions"})
            
            # Validate contract address
            if not client.is_address(contract_address):
                return json.dumps({"error": f"Invalid contract address: {contract_address}"})
            
            checksum_address = client.to_checksum_address(contract_address)
            
            # Create contract instance
            contract = client.eth.contract(address=checksum_address, abi=abi)
            
            # Check if function exists
            if not hasattr(contract.functions, function_name):
                return json.dumps({"error": f"Function {function_name} not found in contract ABI"})
            
            # Get nonce
            nonce = client.eth.get_transaction_count(account.address)
            
            # Get gas price
            gas_price = client.eth.gas_price
            
            # Build transaction
            contract_function = getattr(contract.functions, function_name)
            transaction_builder = contract_function(*function_args)
            
            value_wei = client.to_wei(value_eth, 'ether')
            
            # Build transaction
            transaction = transaction_builder.build_transaction({
                'from': account.address,
                'value': value_wei,
                'nonce': nonce,
                'gasPrice': gas_price,
                'chainId': self._get_network_chain_id(network)
            })
            
            # Estimate gas
            try:
                gas_estimate = client.eth.estimate_gas(transaction)
                transaction['gas'] = gas_estimate
            except ContractLogicError as e:
                # If gas estimation fails, use a default gas limit
                log_error(f"Gas estimation failed: {e}")
                transaction['gas'] = 300000
            
            # Sign and send transaction
            signed_txn = client.eth.account.sign_transaction(transaction, self.private_key)
            tx_hash = client.eth.send_raw_transaction(signed_txn.rawTransaction)
            
            result = {
                "caller": account.address,
                "contract_address": contract_address,
                "function_name": function_name,
                "network": network,
                "transaction_hash": tx_hash.hex(),
                "value_wei": str(value_wei),
                "value_eth": value_eth,
                "gas_price_wei": str(gas_price)
            }
            
            log_info(f"Interacted with contract {contract_address} calling {function_name}")
            return json.dumps(result)
            
        except Exception as e:
            error_msg = f"Error interacting with contract: {str(e)}"
            log_error(error_msg)
            return json.dumps({"error": error_msg})

    def get_gas_price(self, network: Optional[str] = None) -> str:
        """Get current gas price for a network.
        
        Args:
            network: Blockchain network. Supported networks: ethereum, ropsten, rinkeby, 
                   goerli, kovan, polygon, mumbai, binance, bsc-testnet, avalanche, fuji,
                   fantom, cronos, arbitrum, optimism. Defaults to ethereum.
            
        Returns:
            JSON string with gas price information
        """
        try:
            client = self._get_client(network)
            network = network or self.default_network
            
            # Get gas price
            gas_price_wei = client.eth.gas_price
            gas_price_gwei = client.from_wei(gas_price_wei, 'gwei')
            
            result = {
                "network": network,
                "gas_price_wei": str(gas_price_wei),
                "gas_price_gwei": float(gas_price_gwei),
                "chain_id": self._get_network_chain_id(network)
            }
            
            log_info(f"Gas price for {network}: {gas_price_gwei} Gwei")
            return json.dumps(result)
            
        except Exception as e:
            error_msg = f"Error getting gas price: {str(e)}"
            log_error(error_msg)
            return json.dumps({"error": error_msg})

    def estimate_gas(self, to_address: str, value_eth: float = 0, 
                     data: Optional[str] = None, network: Optional[str] = None) -> str:
        """Estimate gas required for a transaction.
        
        Args:
            to_address: Recipient address
            value_eth: Value to send in ETH
            data: Transaction data
            network: Blockchain network. Supported networks: ethereum, ropsten, rinkeby, 
                   goerli, kovan, polygon, mumbai, binance, bsc-testnet, avalanche, fuji,
                   fantom, cronos, arbitrum, optimism. Defaults to ethereum.
            
        Returns:
            JSON string with gas estimation
        """
        try:
            client = self._get_client(network)
            account = self._get_account(network)
            network = network or self.default_network
            
            if not account:
                return json.dumps({"error": "No account configured"})
            
            # Validate address
            if not client.is_address(to_address):
                return json.dumps({"error": f"Invalid address: {to_address}"})
            
            checksum_address = client.to_checksum_address(to_address)
            value_wei = client.to_wei(value_eth, 'ether')
            
            # Build transaction for estimation
            transaction = {
                'from': account.address,
                'to': checksum_address,
                'value': value_wei
            }
            
            if data:
                transaction['data'] = data
            
            # Estimate gas
            gas_estimate = client.eth.estimate_gas(transaction)
            
            result = {
                "network": network,
                "to_address": to_address,
                "value_eth": value_eth,
                "value_wei": str(value_wei),
                "gas_estimate": gas_estimate,
                "chain_id": self._get_network_chain_id(network)
            }
            
            log_info(f"Gas estimate for transaction: {gas_estimate}")
            return json.dumps(result)
            
        except Exception as e:
            error_msg = f"Error estimating gas: {str(e)}"
            log_error(error_msg)
            return json.dumps({"error": error_msg})

    def get_contract_abi(self, contract_address: str, network: Optional[str] = None) -> str:
        """Get contract ABI from a blockchain explorer.
        
        Args:
            contract_address: Address of the contract
            network: Blockchain network. Supported networks: ethereum, ropsten, rinkeby, 
                   goerli, kovan, polygon, mumbai, binance, bsc-testnet, avalanche, fuji,
                   fantom, cronos, arbitrum, optimism. Defaults to ethereum.
            
        Returns:
            JSON string with contract ABI or error message
        """
        try:
            network = network or self.default_network
            
            # Explorer API URLs (simplified - in practice would need API keys)
            explorers = {
                "ethereum": "https://api.etherscan.io/api",
                "polygon": "https://api.polygonscan.com/api",
                "binance": "https://api.bscscan.com/api"
            }
            
            if network not in explorers:
                return json.dumps({"error": f"Explorer API not available for {network}"})
            
            # This is a simplified implementation - in practice would require API keys
            # and proper error handling
            result = {
                "contract_address": contract_address,
                "network": network,
                "note": "ABI retrieval requires API key configuration",
                "supported_explorers": list(explorers.keys())
            }
            
            log_info(f"Requested ABI for contract {contract_address}")
            return json.dumps(result)
            
        except Exception as e:
            error_msg = f"Error getting contract ABI: {str(e)}"
            log_error(error_msg)
            return json.dumps({"error": error_msg})


# Additional utility classes for common blockchain operations

class TokenInfo:
    """Class to hold token information"""
    def __init__(self, address: str, name: str, symbol: str, decimals: int):
        self.address = address
        self.name = name
        self.symbol = symbol
        self.decimals = decimals
    
    def to_dict(self):
        return {
            "address": self.address,
            "name": self.name,
            "symbol": self.symbol,
            "decimals": self.decimals
        }


class TransactionReceipt:
    """Class to hold transaction receipt information"""
    def __init__(self, receipt: Dict[str, Any]):
        self.hash = receipt.get("transactionHash", "").hex()
        self.block_number = receipt.get("blockNumber", 0)
        self.gas_used = receipt.get("gasUsed", 0)
        self.status = "success" if receipt.get("status", 0) == 1 else "failed"
        self.logs = receipt.get("logs", [])
    
    def to_dict(self):
        return {
            "hash": self.hash,
            "block_number": self.block_number,
            "gas_used": self.gas_used,
            "status": self.status,
            "logs": self.logs
        }