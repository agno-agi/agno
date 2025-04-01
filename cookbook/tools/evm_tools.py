from agno.agent import Agent
from agno.tools.evm import EvmTools

private_key= "0x<private-key>"
# Sepolia public rpc url
rpc_url= "https://0xrpc.io/sep"

agent = Agent(
    tools=[
        EvmTools(
            private_key= private_key,
            rpc_url= rpc_url,
        )
    ]
)
agent.print_response("Send  0.001 eth to 0x3Dfc53E3C77bb4e30Ce333Be1a66Ce62558bE395")
