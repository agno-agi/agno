"""
Signed Tool Receipts
====================

Demonstrates how to use agent-level tool_hooks to emit a signed receipt for
both sides of a tool call:

- a pre-execution authorization receipt that commits to the intended call;
- a post-execution settlement receipt that commits to the result.

The receipts are canonical JSON, Ed25519-signed, and hash-chained so they can
be verified offline without trusting the process that originally logged them.

Install the optional signing dependency before running:

    pip install cryptography
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools import tool

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
except ImportError as exc:
    raise ImportError(
        "signed_tool_receipts.py requires cryptography. Install it with: "
        "pip install cryptography"
    ) from exc


Receipt = Dict[str, Any]
receipt_chain: List[Receipt] = []
signing_key = Ed25519PrivateKey.generate()
verify_key = signing_key.public_key()


def canonical_json(value: Any) -> bytes:
    """Return stable JSON bytes for hashing and signing."""
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def receipt_hash(receipt: Receipt) -> str:
    unsigned = {k: v for k, v in receipt.items() if k != "signature"}
    return f"sha256:{sha256_hex(unsigned)}"


def sign_receipt(payload: Receipt) -> Receipt:
    signature = signing_key.sign(canonical_json(payload)).hex()
    return {
        **payload,
        "signature": {
            "alg": "Ed25519",
            "public_key": verify_key.public_bytes(
                encoding=Encoding.Raw,
                format=PublicFormat.Raw,
            ).hex(),
            "sig": signature,
        },
    }


def append_receipt(
    *,
    phase: str,
    tool_name: str,
    decision: str,
    args: Dict[str, Any],
    result: Optional[Any] = None,
    error: Optional[str] = None,
) -> Receipt:
    previous_hash = receipt_hash(receipt_chain[-1]) if receipt_chain else None
    payload: Receipt = {
        "receipt_version": "agno-signed-tool-receipt-v0",
        "sequence": len(receipt_chain) + 1,
        "phase": phase,
        "tool_name": tool_name,
        "decision": decision,
        "args_digest": f"sha256:{sha256_hex(args)}",
        "result_digest": f"sha256:{sha256_hex(result)}" if result is not None else None,
        "error_digest": f"sha256:{sha256_hex(error)}" if error is not None else None,
        "previous_receipt_hash": previous_hash,
        "issued_at": datetime.now(timezone.utc).isoformat(),
    }
    receipt = sign_receipt(payload)
    receipt_chain.append(receipt)
    return receipt


def verify_receipt_chain(receipts: List[Receipt], public_key: Ed25519PublicKey) -> bool:
    previous_hash: Optional[str] = None

    for receipt in receipts:
        signature = receipt["signature"]
        payload = {k: v for k, v in receipt.items() if k != "signature"}

        if payload["previous_receipt_hash"] != previous_hash:
            return False

        public_key.verify(bytes.fromhex(signature["sig"]), canonical_json(payload))
        previous_hash = receipt_hash(receipt)

    return True


def signed_receipt_hook(
    function_name: str, func: Callable[..., Any], args: Dict[str, Any]
) -> Any:
    """Wrap every tool call with signed pre/post receipts."""
    pre = append_receipt(
        phase="pre_execution",
        tool_name=function_name,
        decision="allow",
        args=args,
    )
    print(f"[receipt] pre  #{pre['sequence']} {function_name}: {receipt_hash(pre)}")

    try:
        result = func(**args)
    except Exception as exc:
        post = append_receipt(
            phase="post_execution",
            tool_name=function_name,
            decision="error",
            args=args,
            error=str(exc),
        )
        print(
            f"[receipt] post #{post['sequence']} {function_name}: {receipt_hash(post)}"
        )
        raise

    post = append_receipt(
        phase="post_execution",
        tool_name=function_name,
        decision="settled",
        args=args,
        result=result,
    )
    print(f"[receipt] post #{post['sequence']} {function_name}: {receipt_hash(post)}")
    return result


@tool
def lookup_invoice(invoice_id: str) -> Dict[str, Any]:
    """Look up an invoice by ID."""
    return {
        "invoice_id": invoice_id,
        "customer": "Acme Co",
        "amount_usd": 125,
        "status": "paid",
    }


@tool
def draft_refund(invoice_id: str, amount_usd: int) -> str:
    """Draft a refund action for a paid invoice."""
    return f"Drafted refund for {invoice_id}: ${amount_usd}"


agent = Agent(
    name="Receipts Agent",
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[lookup_invoice, draft_refund],
    tool_hooks=[signed_receipt_hook],
    markdown=True,
)


if __name__ == "__main__":
    agent.print_response(
        "Look up invoice INV-1001 and draft a refund for the full amount.",
        stream=True,
    )

    print("\n--- Signed receipt chain ---")
    print(json.dumps(receipt_chain, indent=2))

    chain_valid = verify_receipt_chain(receipt_chain, verify_key)
    print(f"\nReceipt chain valid: {chain_valid}")
