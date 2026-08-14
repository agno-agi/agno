"""
USDCtoFiat Tools — USDC to fiat cash-out on Base

USDCtoFiat by Galleon Labs. Built on the public Peer/ZKP2P protocol.
Not a Peer Cash product. https://usdctofiat.xyz/developers

UsdctoFiatTools is a small toolkit (<6 functions) so it uses enable_ flags.
mode is required on cashout and estimate: "fast" (0% / TOFIAT) or
"best" (Delegate, 10 bps). There is no default.

The toolkit does not accept a wallet private key. Inject a signer callback
that submits unsigned {to, data, value, chainId} txs, or omit the signer
and cashout() returns the unsigned prepare payload for the host to sign.

Run: `uv pip install usdctofiat` (or `pip install agno[usdctofiat]`)
"""

from agno.agent import Agent
from agno.tools.usdctofiat import UsdctoFiatTools


def signer(tx):
    # Host signs and submits {to, data, value, chainId}. Return the tx hash.
    # Keep the key in *your* runtime. Never pass it to UsdctoFiatTools.
    raise NotImplementedError("inject your wallet signer")


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    tools=[UsdctoFiatTools(signer=signer)],
    description=(
        "You help users cash out Base USDC to fiat via USDCtoFiat by Galleon Labs. "
        "Built on the public Peer/ZKP2P protocol. Not a Peer Cash product."
    ),
    instructions=[
        "Always ask the user to choose mode=fast (0% / TOFIAT) or mode=best (Delegate, 10 bps).",
        "Never invent a mode default. Never ask for or accept a wallet private key.",
        "Fast earns TOFIAT. Best attaches the Delegate rate manager at 10 bps.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Estimate cashing out 100 USDC to EUR on Revolut as alice. I want Fast (0%).",
        markdown=True,
    )
