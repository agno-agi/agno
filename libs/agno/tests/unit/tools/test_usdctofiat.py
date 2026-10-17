"""Mocked unit tests for UsdctoFiatTools."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("usdctofiat")

from usdctofiat import ModeRequired
from usdctofiat.types import CashoutResult, Estimate, PreparedCashout, UnsignedTx

from agno.tools.usdctofiat import UsdctoFiatTools


def _prepared(mode: str = "fast") -> PreparedCashout:
    return PreparedCashout(
        mode=mode,  # type: ignore[arg-type]
        txs=[
            UnsignedTx(to="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", data="0x095ea7b3"),
            UnsignedTx(to="0x777777779d229cdF3110e9de47943791c26300Ef", data="0xcreate"),
        ],
        steps=["approve", "createDeposit"] if mode == "fast" else ["approve", "createDeposit", "setRateManager"],
        payee_details_hash="0x11" + "ab" * 31,
        amount_units=100_000_000,
        platform="revolut",
        currency="EUR",
        attribution={"referral_code": "TOFIAT", "referrers": ["galleonlabs"]},
    )


@pytest.fixture
def mock_offramp():
    client = MagicMock()
    client.prepare.return_value = _prepared("fast")
    client.cashout.return_value = CashoutResult(
        deposit_id="42",
        tx_hash="0x" + "ab" * 32,
        mode="fast",
        tx_hashes=["0x" + "ab" * 32],
        prepared=_prepared("fast"),
    )
    client.estimate.return_value = Estimate(
        mode="fast",
        amount_units=100_000_000,
        currency="EUR",
        rate="1",
        receive_amount="100",
        spread_bps=0,
        manager_fee_bps=0,
    )
    client.deposits.return_value = [{"id": "42", "status": "ACTIVE"}]
    client.watch.return_value = iter([{"id": "42", "status": "ACTIVE"}])
    client.withdraw.return_value = UnsignedTx(
        to="0x777777779d229cdF3110e9de47943791c26300Ef",
        data="0xwithdraw",
    )
    return client


@pytest.fixture
def tools(mock_offramp):
    with patch("agno.tools.usdctofiat.create_offramp", return_value=mock_offramp):
        yield UsdctoFiatTools(), mock_offramp


def test_docstring_discloses_product_and_docs():
    import agno.tools.usdctofiat as module

    text = f"{UsdctoFiatTools.__doc__ or ''} {module.__doc__ or ''}".lower()
    assert "usdctofiat" in text
    assert "galleon" in text
    assert "usdctofiat.xyz/developers" in text


def test_mode_is_not_a_constructor_default(mock_offramp):
    with patch("agno.tools.usdctofiat.create_offramp", return_value=mock_offramp):
        with pytest.raises(TypeError, match="does not default mode"):
            UsdctoFiatTools(mode="fast")
        with pytest.raises(TypeError, match="does not default mode"):
            UsdctoFiatTools(mode="best")
        UsdctoFiatTools()  # unset is fine


def test_no_private_key_constructor(mock_offramp):
    with patch("agno.tools.usdctofiat.create_offramp", return_value=mock_offramp):
        with pytest.raises(TypeError, match="does not accept a private key"):
            UsdctoFiatTools(private_key="0xabc")
        with pytest.raises(TypeError, match="does not accept a private key"):
            UsdctoFiatTools(evm_private_key="0xabc")
        kit = UsdctoFiatTools()
        assert not hasattr(kit, "private_key")
        assert kit.signer is None


def test_enable_flags_register_selected_tools_only(mock_offramp):
    with patch("agno.tools.usdctofiat.create_offramp", return_value=mock_offramp):
        kit = UsdctoFiatTools(
            enable_cashout=True,
            enable_watch=False,
            enable_withdraw=False,
            enable_deposits=False,
            enable_estimate=True,
        )
        assert set(kit.functions) == {"cashout", "estimate"}
        assert {t.__name__ for t in kit.tools} == {"cashout", "estimate"}


def test_cashout_without_signer_returns_unsigned_prepare(tools):
    kit, offramp = tools
    payload = json.loads(kit.cashout(mode="fast", amount="100", currency="EUR", platform="revolut", payee="alice"))
    assert payload["signed"] is False
    assert payload["prepared"]["mode"] == "fast"
    assert payload["prepared"]["steps"] == ["approve", "createDeposit"]
    assert payload["prepared"]["attribution"]["referral_code"] == "TOFIAT"
    offramp.prepare.assert_called_once()
    offramp.cashout.assert_not_called()


def test_cashout_with_injected_signer(mock_offramp):
    def signer(tx):
        return {"hash": "0x" + "cd" * 32, "deposit_id": "42"}

    with patch("agno.tools.usdctofiat.create_offramp", return_value=mock_offramp):
        kit = UsdctoFiatTools(signer=signer)
        payload = json.loads(kit.cashout(mode="fast", amount="10", currency="GBP", platform="monzo", payee="alice"))
        assert payload["signed"] is True
        assert payload["result"]["deposit_id"] == "42"
        assert payload["result"]["mode"] == "fast"
        mock_offramp.cashout.assert_called_once()
        kwargs = mock_offramp.cashout.call_args.kwargs
        assert kwargs["mode"] == "fast"
        assert kwargs["signer"] is signer


def test_cashout_mode_required_is_returned_as_json(tools):
    kit, offramp = tools
    offramp.prepare.side_effect = ModeRequired()
    payload = json.loads(kit.cashout(mode="", amount="100", currency="EUR", platform="revolut", payee="alice"))
    assert "mode is required" in payload["error"]
    assert payload["code"] == "VALIDATION"


def test_estimate_watch_withdraw_deposits(tools):
    kit, offramp = tools
    estimate = json.loads(kit.estimate(mode="fast", amount="100", currency="EUR"))
    assert estimate["spread_bps"] == 0
    assert estimate["manager_fee_bps"] == 0
    assert estimate["mode"] == "fast"

    watched = json.loads(kit.watch("42"))
    assert watched["snapshots"][0]["status"] == "ACTIVE"

    rows = json.loads(kit.deposits("0x1111111111111111111111111111111111111111"))
    assert rows["deposits"][0]["id"] == "42"

    withdrawn = json.loads(kit.withdraw("42"))
    assert withdrawn["to"].lower().endswith("ef")
    closed = json.loads(kit.close("42"))
    assert closed["data"] == "0xwithdraw"


def test_estimate_mode_required(tools):
    kit, offramp = tools
    offramp.estimate.side_effect = ModeRequired()
    payload = json.loads(kit.estimate(mode="slow", amount="100", currency="EUR"))
    assert "mode is required" in payload["error"]


def test_attribution_kwargs_rejected(mock_offramp):
    with patch("agno.tools.usdctofiat.create_offramp", return_value=mock_offramp) as factory:
        for key, value in (
            ("referrer", "evil.eth"),
            ("referrers", ["evil.eth"]),
            ("extra_referrers", ["evil.eth"]),
            ("referral_code", "EVIL"),
        ):
            with pytest.raises(TypeError, match="does not accept attribution"):
                UsdctoFiatTools(**{key: value})
        factory.assert_not_called()
        UsdctoFiatTools()
        factory.assert_called_once_with()


def test_allowed_host_kwargs_still_forward(mock_offramp):
    with patch("agno.tools.usdctofiat.create_offramp", return_value=mock_offramp) as factory:
        UsdctoFiatTools(curator_url="https://curator.example", indexer_url="https://indexer.example")
        factory.assert_called_once_with(
            curator_url="https://curator.example",
            indexer_url="https://indexer.example",
        )


def test_async_twins_registered(mock_offramp):
    with patch("agno.tools.usdctofiat.create_offramp", return_value=mock_offramp):
        kit = UsdctoFiatTools()
        assert set(kit.functions) == {"cashout", "watch", "withdraw", "close", "deposits", "estimate"}
        assert set(kit.async_functions) == set(kit.functions)
        kit_partial = UsdctoFiatTools(
            enable_cashout=True,
            enable_watch=False,
            enable_withdraw=False,
            enable_deposits=False,
            enable_estimate=True,
        )
        assert set(kit_partial.functions) == {"cashout", "estimate"}
        assert set(kit_partial.async_functions) == {"cashout", "estimate"}


@pytest.mark.asyncio
async def test_acashout_without_signer_returns_unsigned_prepare(tools):
    kit, offramp = tools
    payload = json.loads(
        await kit.acashout(mode="fast", amount="100", currency="EUR", platform="revolut", payee="alice")
    )
    assert payload["signed"] is False
    assert payload["prepared"]["attribution"]["referral_code"] == "TOFIAT"
    offramp.prepare.assert_called_once()
    offramp.cashout.assert_not_called()
