"""
EVM Tools Example

This example demonstrates how to use Agno's EVM integration to send ETH transactions
on any EVM-compatible blockchain.

1. Set your environment variables:
    export EVM_PRIVATE_KEY=0x<your-private-key>
    export EVM_RPC_URL=https://your-rpc-endpoint

2. Or pass them directly to the EvmTools constructor
3. Install dependencies:
    pip install agno web3
"""

from agno.agent import Agent
from agno.tools.evm import EvmTools

# Option 1: Use environment variables (recommended)
agent = Agent(
    tools=[EvmTools()],  # Will use EVM_PRIVATE_KEY and EVM_RPC_URL from env
)

# Option 2: Pass credentials directly (for testing only)
# private_key = "0x<private-key>"
# rpc_url = "https://0xrpc.io/sep"  # Sepolia testnet
# agent = Agent(
#     tools=[
#         EvmTools(
#             private_key=private_key,
#             rpc_url=rpc_url,
#         )
#     ],
# )

# Convert 0.001 ETH to wei (1 ETH = 10^18 wei)
# 0.001 ETH = 1,000,000,000,000,000 wei
agent.print_response(
    "Send 0.001 eth (which is 1000000000000000 wei) to address 0x3Dfc53E3C77bb4e30Ce333Be1a66Ce62558bE395"
)
