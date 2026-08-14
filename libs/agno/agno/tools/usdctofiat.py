"""UsdctoFiatTools — first-party Agno toolkit.

USDCtoFiat by Galleon Labs. Built on the public Peer/ZKP2P protocol.
Not a Peer Cash product. https://usdctofiat.xyz/developers

Wraps `usdctofiat.cashout(mode="fast"|"best")`, `watch`, `withdraw`/`close`,
`deposits`, and `estimate`. Mode is required on every priced or mutating call.
There is no default to Fast or Best. This toolkit never accepts a wallet
private key — inject a signer callback, or call cashout without one to
receive unsigned `{to, data, value, chainId}` txs.

Install: `pip install usdctofiat` or `pip install agno[usdctofiat]`.
"""

from __future__ import annotations

import json
from typing import Any, Callable, List, Optional

from agno.tools import Toolkit

try:
    from usdctofiat import create_offramp
    from usdctofiat.errors import UsdctoFiatError
    from usdctofiat.types import CashoutResult, Estimate, PreparedCashout, UnsignedTx
except ImportError as exc:
    raise ImportError("`usdctofiat` not installed. Please install using `pip install usdctofiat`") from exc

_BANNED_KEY_KWARGS = (
    "private_key",
    "privateKey",
    "key",
    "secret",
    "mnemonic",
    "wallet_key",
    "evm_private_key",
    "EVM_PRIVATE_KEY",
)


class UsdctoFiatTools(Toolkit):
    """USDCtoFiat tools for Agno agents. Galleon Labs. Not Peer Cash.

    Args:
        signer: Optional callback `(unsigned_tx) -> hash | {hash, deposit_id}`.
            Kept in the host runtime. Never a private key.
        enable_cashout / enable_watch / enable_withdraw / enable_deposits /
            enable_estimate: register each function behind an `enable_*` flag.
        all: enable every function regardless of individual flags.
    """

    def __init__(
        self,
        signer: Optional[Callable[[Any], Any]] = None,
        enable_cashout: bool = True,
        enable_watch: bool = True,
        enable_withdraw: bool = True,
        enable_deposits: bool = True,
        enable_estimate: bool = True,
        all: bool = False,
        mode: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        for banned in _BANNED_KEY_KWARGS:
            if banned in kwargs:
                raise TypeError(
                    "UsdctoFiatTools does not accept a private key. "
                    "Inject a signer callback or call cashout without a signer "
                    "to receive unsigned txs."
                )
        if mode is not None:
            raise TypeError(
                "UsdctoFiatTools does not default mode. "
                'Pass mode="fast" (0% / TOFIAT) or mode="best" (Delegate, 10 bps) '
                "on each cashout/estimate call."
            )

        self.signer = signer
        self.offramp = create_offramp(
            **{
                key: kwargs.pop(key)
                for key in (
                    "curator_url",
                    "indexer_url",
                    "curator",
                    "indexer",
                    "referrer",
                    "referrers",
                    "extra_referrers",
                    "referral_code",
                )
                if key in kwargs
            }
        )

        tools: List[Any] = []
        if all or enable_cashout:
            tools.append(self.cashout)
        if all or enable_watch:
            tools.append(self.watch)
        if all or enable_withdraw:
            tools.append(self.withdraw)
            tools.append(self.close)
        if all or enable_deposits:
            tools.append(self.deposits)
        if all or enable_estimate:
            tools.append(self.estimate)

        super().__init__(name="usdctofiat", tools=tools, **kwargs)

    def cashout(
        self,
        mode: str,
        amount: str,
        currency: str,
        platform: str,
        payee: str,
    ) -> str:
        """Cash out Base USDC to fiat via USDCtoFiat by Galleon Labs.

        mode is required. There is no default.
        - fast: 0% spread / 0 bps. We earn TOFIAT.
        - best: Delegate, 10 bps.

        If a signer was injected, unsigned txs are submitted and the deposit
        id / tx hash are returned. Otherwise this returns unsigned
        {to, data, value, chainId} txs for the host to sign. Never pass a
        wallet private key to this toolkit.

        Args:
            mode: "fast" or "best". Required.
            amount: Human USDC amount (string or number). An int is six-decimal units.
            currency: Fiat ISO code, e.g. EUR, USD, GBP.
            platform: Payment rail, e.g. revolut, venmo, monzo.
            payee: Handle on that platform.

        Returns:
            JSON string with the cash-out result or unsigned prepare payload.
        """
        try:
            if self.signer is None:
                prepared = self.offramp.prepare(
                    mode=mode,
                    amount=amount,
                    currency=currency,
                    platform=platform,
                    payee=payee,
                )
                return _dumps({"prepared": _as_dict(prepared), "signed": False})
            result = self.offramp.cashout(
                mode=mode,
                amount=amount,
                currency=currency,
                platform=platform,
                payee=payee,
                signer=self.signer,
            )
            return _dumps({"result": _as_dict(result), "signed": True})
        except Exception as exc:
            return _error(exc)

    def watch(self, deposit_id: str) -> str:
        """Watch a USDCtoFiat deposit by id (indexer snapshot).

        Args:
            deposit_id: Fast composite resume key or Best numeric EscrowV2 id.

        Returns:
            JSON list of deposit snapshots.
        """
        try:
            rows = list(self.offramp.watch(deposit_id))
            return _dumps({"deposit_id": deposit_id, "snapshots": rows})
        except Exception as exc:
            return _error(exc)

    def withdraw(self, deposit_id: str) -> str:
        """Withdraw / close a USDCtoFiat deposit.

        Returns a signed result when a signer is injected, otherwise the
        unsigned withdraw tx.

        Args:
            deposit_id: EscrowV2 deposit id.
        """
        try:
            result = self.offramp.withdraw(deposit_id, signer=self.signer)
            return _dumps(_as_dict(result))
        except Exception as exc:
            return _error(exc)

    def close(self, deposit_id: str) -> str:
        """Alias of withdraw. Unwind a Best (or Fast) deposit."""
        return self.withdraw(deposit_id)

    def deposits(self, owner: str) -> str:
        """List USDCtoFiat deposits for an owner address.

        Args:
            owner: 0x depositor on Base.
        """
        try:
            return _dumps({"owner": owner, "deposits": self.offramp.deposits(owner)})
        except Exception as exc:
            return _error(exc)

    def estimate(self, mode: str, amount: str, currency: str) -> str:
        """Estimate a USDCtoFiat cash-out. Not a locked quote.

        mode is required. fast = 0 bps seller spread. best = 10 bps manager fee.

        Args:
            mode: "fast" or "best". Required.
            amount: Human USDC amount.
            currency: Fiat ISO code.
        """
        try:
            return _dumps(_as_dict(self.offramp.estimate(mode=mode, amount=amount, currency=currency)))
        except Exception as exc:
            return _error(exc)


def _as_dict(value: Any) -> Any:
    if isinstance(value, (CashoutResult, PreparedCashout, Estimate, UnsignedTx)):
        return value.as_dict()
    if hasattr(value, "as_dict"):
        return value.as_dict()
    return value


def _dumps(payload: Any) -> str:
    return json.dumps(payload, indent=2, default=str)


def _error(exc: Exception) -> str:
    payload: dict[str, Any] = {"error": str(exc), "code": getattr(exc, "code", type(exc).__name__)}
    if isinstance(exc, UsdctoFiatError) and exc.details is not None:
        payload["details"] = exc.details
    return _dumps(payload)
