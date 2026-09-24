"""
Structured Extraction - Nested Records
======================================

Build a nested order snapshot while applying amendments, cancellations, and
stable output ordering.
"""

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from pydantic import BaseModel, Field


class LineItem(BaseModel):
    sku: str
    quantity: int = Field(ge=1)
    unit_price_cents: int = Field(ge=0)


class ShipmentItem(BaseModel):
    sku: str
    quantity: int = Field(ge=1)


class Shipment(BaseModel):
    shipment_id: str
    items: list[ShipmentItem]


class OrderSnapshot(BaseModel):
    order_id: str
    currency: str
    items: list[LineItem]
    shipments: list[Shipment]
    unshipped_items: list[ShipmentItem]
    applied_event_ids: list[str]


def snapshot_matches(run, expected) -> bool:
    return (
        isinstance(run.content, OrderSnapshot) and run.content.model_dump() == expected
    )


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    output_schema=OrderSnapshot,
    instructions=(
        "Extract the current order only. Confirmed amendments replace the named "
        "line, while omitted lines remain. Cancelled lines and voided shipments are "
        "excluded. A shipment contains only current item quantities; when a shipment "
        "names a SKU without a quantity, it contains that line's full current quantity. "
        "Ignore quoted records "
        "for other orders. Sort items by SKU, shipments by shipment_id, and each "
        "shipment's items by SKU. Convert decimal prices to integer cents. Return "
        "unshipped_items sorted by SKU with each current order quantity minus its "
        "non-voided shipment allocations, omitting zero balances. Return "
        "applied_event_ids in chronological order for every labeled operative "
        "amendment, cancellation, void, replacement, or repack that changes the final "
        "snapshot; omit initial declarations and non-operative proposals."
    ),
)

environment = Environment(
    name="nested-order-snapshots",
    agent=agent,
    tasks=(
        Task(
            id="amended-split-shipment",
            input=(
                "Current order O-71, USD: line K-2 qty 3 at $19.95; line A-9 qty 1 "
                "at $240.00; line B-4 qty 2 at $7.50. Confirmed amendment A1 replaces "
                "K-2 with qty 4 at $18.75 and cancels B-4. Shipment S-20 contains "
                "K-2 and B-4. Shipment S-03 contains A-9. Revised packing event P1 "
                "removes cancelled B-4. "
                "Quoted old order O-70 had K-2 at $17.00."
            ),
            expected={
                "order_id": "O-71",
                "currency": "USD",
                "items": [
                    {"sku": "A-9", "quantity": 1, "unit_price_cents": 24000},
                    {"sku": "K-2", "quantity": 4, "unit_price_cents": 1875},
                ],
                "shipments": [
                    {
                        "shipment_id": "S-03",
                        "items": [{"sku": "A-9", "quantity": 1}],
                    },
                    {
                        "shipment_id": "S-20",
                        "items": [{"sku": "K-2", "quantity": 4}],
                    },
                ],
                "unshipped_items": [],
                "applied_event_ids": ["A1"],
            },
        ),
        Task(
            id="voided-and-repacked",
            input=(
                "Order R-8, EUR: C qty 2 at EUR 12.40, A qty 5 at EUR 3.05, B qty "
                "1 at EUR 99.99. Amendment A1 changes A to qty 4, price unchanged. "
                "Void event V1 marks shipment Z9 with A and C VOIDED. Replacement "
                "event R1 creates shipment Z10 with C. Shipment Z2 has B and A, but "
                "final repack P1 moves A to Z10; Z2 now has "
                "only B. A proposed cancellation of C was not confirmed."
            ),
            expected={
                "order_id": "R-8",
                "currency": "EUR",
                "items": [
                    {"sku": "A", "quantity": 4, "unit_price_cents": 305},
                    {"sku": "B", "quantity": 1, "unit_price_cents": 9999},
                    {"sku": "C", "quantity": 2, "unit_price_cents": 1240},
                ],
                "shipments": [
                    {
                        "shipment_id": "Z10",
                        "items": [
                            {"sku": "A", "quantity": 4},
                            {"sku": "C", "quantity": 2},
                        ],
                    },
                    {
                        "shipment_id": "Z2",
                        "items": [{"sku": "B", "quantity": 1}],
                    },
                ],
                "unshipped_items": [],
                "applied_event_ids": ["A1", "V1", "R1", "P1"],
            },
        ),
        Task(
            id="partial-allocation-repack",
            input=(
                "Order X-42, GBP: A qty 7 at GBP 10.10, B qty 5 at GBP 4.25, "
                "C qty 2 at GBP 80.00, D qty 1 at GBP 3.00. Confirmed amendment A1 "
                "sets A qty 8 and B qty 6, and cancels D. Later confirmed amendment "
                "A2 changes only B to qty 4. Void event V1 marks shipment S0, which "
                "listed D, voided. Initial "
                "shipment S1 allocates A qty 3 and B qty 2. Shipment S2 allocates A "
                "qty 5 and C qty 2. Shipment S3 allocates B qty 2. Final repack P1 moves "
                "one unit of B from S1 to S3, leaving all other allocations unchanged."
            ),
            expected={
                "order_id": "X-42",
                "currency": "GBP",
                "items": [
                    {"sku": "A", "quantity": 8, "unit_price_cents": 1010},
                    {"sku": "B", "quantity": 4, "unit_price_cents": 425},
                    {"sku": "C", "quantity": 2, "unit_price_cents": 8000},
                ],
                "shipments": [
                    {
                        "shipment_id": "S1",
                        "items": [
                            {"sku": "A", "quantity": 3},
                            {"sku": "B", "quantity": 1},
                        ],
                    },
                    {
                        "shipment_id": "S2",
                        "items": [
                            {"sku": "A", "quantity": 5},
                            {"sku": "C", "quantity": 2},
                        ],
                    },
                    {
                        "shipment_id": "S3",
                        "items": [{"sku": "B", "quantity": 3}],
                    },
                ],
                "unshipped_items": [],
                "applied_event_ids": ["A1", "A2", "P1"],
            },
        ),
        Task(
            id="multi-stage-fulfillment",
            input=(
                "Order F-900, USD: A qty 10 at $1.11, B qty 8 at $2.22, C qty "
                "6 at $3.33, D qty 4 at $4.44, E qty 3 at $5.55. Amendment A1 "
                "sets A to 12, cancels B, sets C to 5, and adds F qty 7 at $6.66. "
                "Amendment A2 restores B at qty 2, sets D to 5, and cancels E. "
                "Initial shipment S1 has A5,C2,D1. Initial shipment S2 has A4,F3,B2. "
                "Initial shipment S3 has C2,D2. Void event V1 voids S2. Replacement "
                "event R1 creates S4 with A4,F3,B2. Repack event P1 moves one C from "
                "S1 to S3. Shipment S5 has F2. No other units have shipped."
            ),
            expected={
                "order_id": "F-900",
                "currency": "USD",
                "items": [
                    {"sku": "A", "quantity": 12, "unit_price_cents": 111},
                    {"sku": "B", "quantity": 2, "unit_price_cents": 222},
                    {"sku": "C", "quantity": 5, "unit_price_cents": 333},
                    {"sku": "D", "quantity": 5, "unit_price_cents": 444},
                    {"sku": "F", "quantity": 7, "unit_price_cents": 666},
                ],
                "shipments": [
                    {
                        "shipment_id": "S1",
                        "items": [
                            {"sku": "A", "quantity": 5},
                            {"sku": "C", "quantity": 1},
                            {"sku": "D", "quantity": 1},
                        ],
                    },
                    {
                        "shipment_id": "S3",
                        "items": [
                            {"sku": "C", "quantity": 3},
                            {"sku": "D", "quantity": 2},
                        ],
                    },
                    {
                        "shipment_id": "S4",
                        "items": [
                            {"sku": "A", "quantity": 4},
                            {"sku": "B", "quantity": 2},
                            {"sku": "F", "quantity": 3},
                        ],
                    },
                    {
                        "shipment_id": "S5",
                        "items": [{"sku": "F", "quantity": 2}],
                    },
                ],
                "unshipped_items": [
                    {"sku": "A", "quantity": 3},
                    {"sku": "C", "quantity": 1},
                    {"sku": "D", "quantity": 2},
                    {"sku": "F", "quantity": 2},
                ],
                "applied_event_ids": ["A1", "A2", "V1", "R1", "P1"],
            },
        ),
    ),
    scorer=CodeScorer(snapshot_matches),
)


if __name__ == "__main__":
    results = run_rollouts(environment, k=4, concurrency=4)
    print(results)
    for task_result in results.task_results:
        print(f"{task_result.task.id}: {task_result.n_passed}/{task_result.n_scored}")
