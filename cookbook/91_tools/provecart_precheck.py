"""ProveCart precheck: never let an agent pay for the wrong cart.

Cookbook recipe: a shopping agent builds a cart; before the payment
tool may run, the cart is checked with ProveCart against what the
customer actually asked for (the signed mandate).

- MATCH  -> payment may proceed.
- BLOCK  -> the check returns the exact corrections (wrong item,
  over the price ceiling, too many). Apply only the repairs that
  stay inside the customer's authorization and re-check — the
  correction loop (Agent Correction Format, ACF v0.2).
- REVIEW -> stop and ask the buyer. Never guess.

Run the deterministic demo (no model key needed):

    export PROVECART_API_KEY=<your integrator key>
    python provecart_precheck.py

Get a key from ProveCart — or, if you are an agent, take the free
Verified Agent exam first: https://provecart.com/agents
"""

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from agno.tools import Toolkit

BASE = os.environ.get("PROVECART_BASE_URL", "https://api.provecart.com")

KNOWN_ACTIONS = {
    "remove_item", "replace_item", "change_variant", "reduce_quantity",
    "reduce_total", "change_currency", "correct_traveler_name",
    "change_airport", "change_travel_date", "change_departure_time",
    "add_itinerary", "rebuild_itinerary", "change_cabin",
    "change_fare_terms", "add_hotel_stay", "change_room",
    "change_provider", "change_location", "change_date", "change_time",
    "change_party_size", "correct_reservation_name", "reduce_deposit",
    "change_cancellation_terms",
}


def _post(path, body):
    req = urllib.request.Request(
        BASE.rstrip("/") + path, data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json",
                 "X-API-Key": os.environ["PROVECART_API_KEY"]})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"ProveCart {path} -> {e.code}")


def create_mandate(instruction: dict) -> dict:
    """Create the signed mandate a cart will be checked against."""
    return _post("/mandates", instruction)


def verify_cart(mandate_id, merchant, items, total_price,
                previous_record_id=None):
    body = {"mandate_id": mandate_id, "merchant": merchant,
            "items": items, "total_price": total_price,
            "currency": "USD",
            "cart_changed": bool(previous_record_id)}
    if previous_record_id:
        body["previous_record_id"] = previous_record_id
    return _post("/verify", body)


class ProveCartTools(Toolkit):
    """Give any Agno agent the pre-payment check as a tool."""

    def __init__(self):
        super().__init__(name="provecart_tools",
                         tools=[self.check_cart_before_payment])

    def check_cart_before_payment(
        self, mandate_id: str, merchant_name: str, items_json: str,
        total_price: float, previous_record_id: str = "",
    ) -> str:
        """Check a built cart with ProveCart BEFORE paying.

        Args:
            mandate_id: mandate created from the customer's request.
            merchant_name: store the cart was built at.
            items_json: cart items as JSON: [{"name", "quantity",
                "unit_price", "category"}].
            total_price: cart grand total.
            previous_record_id: set when resubmitting a fixed cart.

        Returns MATCH (safe to pay), BLOCK with the corrections to
        apply, or REVIEW (stop and ask the buyer).
        """
        out = verify_cart(mandate_id, {"name": merchant_name},
                          json.loads(items_json), total_price,
                          previous_record_id or None)
        verdict = out.get("verdict")
        if verdict == "MATCH":
            return (f"MATCH (record {out.get('record_id')}): safe to "
                    "pay.")
        if verdict == "BLOCK":
            corrections = out.get("corrections") or []
            if corrections and all(
                    c.get("action") in KNOWN_ACTIONS
                    for c in corrections):
                return ("BLOCK (record "
                        f"{out.get('record_id')}): do NOT pay. Apply "
                        "only these corrections, then call again "
                        f"with previous_record_id: "
                        f"{json.dumps(corrections)}")
            return "BLOCK: do NOT pay; escalate to the buyer."
        return f"{verdict}: stop and ask the buyer before paying."


def demo():
    instruction = {
        "user_id": "demo-buyer",
        "item_description": "Sony WH-1000XM5 wireless noise "
                            "cancelling headphones",
        "item_keywords": ["sony", "wh-1000xm5", "headphones"],
        "category": "headphones", "max_total_price": 300.0,
        "currency": "USD", "max_quantity": 1,
        "expires_at": (datetime.now(timezone.utc)
                       + timedelta(days=30)).isoformat()
                      .replace("+00:00", "Z"),
    }
    mandate = create_mandate(instruction)
    merchant = {"name": "Example Store", "domain": "example.com"}
    bad = ([{"name": "BassPro Q9 Wireless Headphones", "quantity": 2,
             "unit_price": 189.0, "category": "headphones"}], 378.0)
    good = ([{"name": "Sony WH-1000XM5 wireless noise cancelling "
               "headphones", "quantity": 1, "unit_price": 299.0,
              "category": "headphones"}], 299.0)
    tools = ProveCartTools()
    previous = ""
    for label, (items, total) in [("v1", bad), ("v2", good)]:
        answer = tools.check_cart_before_payment(
            mandate["id"], "Example Store", json.dumps(items), total,
            previous)
        print(f"cart {label}: {answer}")
        if answer.startswith("MATCH"):
            print("Payment may proceed.")
            return
        previous = answer.split("record ")[1].split(")")[0]
    print("Stopped: no MATCH within the correction budget.")


if __name__ == "__main__":
    demo()
