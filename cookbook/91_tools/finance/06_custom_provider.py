"""
Bring Your Own Provider
=======================
A provider is a `FinanceProvider` subclass that declares which capabilities
it serves and returns the normalized dataclasses from `agno.tools.finance`.
FinanceTools registers only the tools the provider declares, serializes the
dataclasses to JSON, and turns any `FinanceProviderError` into a clean
`{"error": ...}` payload for the model.

This example wraps an internal price table (a dict here; a database, a
data lake or a broker API in real life). It serves `get_quote` and
`search_symbols` only, and registers itself under the id "internal" so it
can also be selected by id with `FinanceTools(provider="internal")`.
"""

from typing import List

from agno.agent import Agent
from agno.tools.finance import (
    FinanceProvider,
    FinanceProviderError,
    FinanceTools,
    ProviderStatus,
    Quote,
    SymbolMatch,
    register_provider,
)

# ---------------------------------------------------------------------------
# A tiny in-house data source
# ---------------------------------------------------------------------------
PRICES = {
    "ACME": {"name": "Acme Robotics", "price": 41.25, "previous_close": 40.10},
    "GLOBX": {"name": "Globex Corporation", "price": 128.4, "previous_close": 130.0},
}


class InternalPrices(FinanceProvider):
    id = "internal"
    name = "Internal price table"
    capabilities = frozenset({"get_quote", "search_symbols"})

    def status(self) -> ProviderStatus:
        return ProviderStatus(ok=True, detail=f"{len(PRICES)} symbols loaded")

    def search_symbols(self, query: str, limit: int = 5) -> List[SymbolMatch]:
        needle = query.lower()
        hits = [
            SymbolMatch(
                symbol=symbol, name=row["name"], exchange="INTERNAL", type="EQUITY"
            )
            for symbol, row in PRICES.items()
            if needle in symbol.lower() or needle in row["name"].lower()
        ]
        return hits[:limit]

    def get_quote(self, symbol: str) -> Quote:
        row = PRICES.get(symbol)
        if row is None:
            raise FinanceProviderError(f"{symbol} is not in the internal price table")
        change = round(row["price"] - row["previous_close"], 4)
        return Quote(
            symbol=symbol,
            name=row["name"],
            price=row["price"],
            previous_close=row["previous_close"],
            change=change,
            change_percent=round(change / row["previous_close"] * 100, 4),
            currency="USD",
            as_of="2026-08-18T16:00:00+00:00",
        )


register_provider("internal", InternalPrices)

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Desk Agent",
    model="openai:gpt-5.6",
    tools=[FinanceTools(provider=InternalPrices())],
    instructions="Answer from the internal price table only. If a symbol is unknown, say so.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(FinanceTools(provider="internal"))
    agent.print_response("How did Acme and Globex close today?", stream=True)
