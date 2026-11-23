"""
Structured Extraction - Conflicting Fields
==========================================

Resolve fields from sources with different authority rather than copying the
last value mentioned in the prompt.
"""

from typing import Literal

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from pydantic import BaseModel


class ShipmentRecord(BaseModel):
    shipment_id: str
    destination_country: str
    service: Literal["ground", "priority", "express"]
    declared_value_usd: int
    signature_required: bool
    source_by_field: dict[str, str]
    discarded_source_ids: list[str]
    discarded_source_checksum: int


def shipment_matches(run, expected) -> bool:
    return (
        isinstance(run.content, ShipmentRecord) and run.content.model_dump() == expected
    )


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    output_schema=ShipmentRecord,
    instructions=(
        "Reconcile one shipment. Apply this total precedence per field: the latest "
        "signed shipping correction, then carrier acceptance scan, then printed "
        "label, then manifest. When timestamps are provided, latest means the greatest "
        "effective timestamp, not mention order. A source changes only fields it "
        "explicitly supplies; neither changes declared value or signature terms "
        "unless it states that field. "
        "Unsigned chat, planned changes, voided scans, and quoted history are not "
        "operative. Return source_by_field for destination_country, service, "
        "declared_value_usd, and signature_required using exact source ids. Also "
        "return every explicitly non-operative source id in lexical order; do not "
        "include lower-precedence sources that remain valid fallbacks. For the audit "
        "checksum, take each discarded id's numeric suffix n at one-based lexical "
        "position i and set h0=271828+sum(i*n). For r=1 through 8, set "
        "h_r=(h_(r-1)^2+97*r+31) mod 10000019. Return h_8."
    ),
)

environment = Environment(
    name="conflicting-shipment-fields",
    agent=agent,
    tasks=(
        Task(
            id="scan-and-correction",
            input=(
                "Manifest M for SH-81: Canada, ground, declared $900, signature required. "
                "Printed label L: United States, priority. Carrier acceptance scan S: "
                "Canada, express. Signed correction C1 changes only declared value to "
                "$750 and says nothing about other fields. Unsigned chat U1 says "
                "remove signature, but the request is pending."
            ),
            expected={
                "shipment_id": "SH-81",
                "destination_country": "Canada",
                "service": "express",
                "declared_value_usd": 750,
                "signature_required": True,
                "source_by_field": {
                    "destination_country": "S",
                    "service": "S",
                    "declared_value_usd": "C1",
                    "signature_required": "M",
                },
                "discarded_source_ids": ["U1"],
                "discarded_source_checksum": 8635946,
            },
        ),
        Task(
            id="voided-later-scan",
            input=(
                "Manifest M for SH-205: Germany, express, declared $1200, no signature. "
                "Signed correction C1 changes service to priority and requires a "
                "signature. Acceptance scan S8 records Germany, ground. Scan S9 "
                "records France, express but is marked VOIDED duplicate. Warehouse "
                "note W1 plans a $1000 declaration but no correction was signed."
            ),
            expected={
                "shipment_id": "SH-205",
                "destination_country": "Germany",
                "service": "priority",
                "declared_value_usd": 1200,
                "signature_required": True,
                "source_by_field": {
                    "destination_country": "S8",
                    "service": "C1",
                    "declared_value_usd": "M",
                    "signature_required": "C1",
                },
                "discarded_source_ids": ["S9", "W1"],
                "discarded_source_checksum": 6175153,
            },
        ),
        Task(
            id="narrow-latest-correction",
            input=(
                "Manifest M for SH-9: Japan, priority, declared $640, signature required. "
                "Acceptance scan S: South Korea, express. Signed correction C1 says "
                "destination Japan and declared value $500. Later signed correction "
                "C2 says only 'declared value restored to $640; C1 otherwise stands.' "
                "Email E1 quotes the scan and asks whether Korea might be correct."
            ),
            expected={
                "shipment_id": "SH-9",
                "destination_country": "Japan",
                "service": "express",
                "declared_value_usd": 640,
                "signature_required": True,
                "source_by_field": {
                    "destination_country": "C1",
                    "service": "S",
                    "declared_value_usd": "C2",
                    "signature_required": "M",
                },
                "discarded_source_ids": ["E1"],
                "discarded_source_checksum": 8635946,
            },
        ),
        Task(
            id="timestamped-source-audit",
            input=(
                "Manifest M0 for SH-777: Spain, ground, declared $2000, no "
                "signature. Printed label L1: Portugal, priority. Acceptance scan S1: "
                "Italy, express. Signed correction C13 effective 12:20 changes only "
                "service to express. Quoted history Q03 says no signature; unsigned "
                "chat U01 says value $1600; planned change P02 says Belgium. Signed "
                "correction C10 effective 10:30 changes declared value to $1800 and "
                "requires signature. Voided scan S09 says Netherlands, ground; planned "
                "label P05 says Sweden; quoted manifest Q07 says Norway and $100. "
                "Signed correction C14 effective 12:25 changes only declared value to "
                "$1700. Unsigned chat U04 says service ground; voided scan S06 says "
                "Denmark; planned unsigned correction P09 says priority. Signed "
                "correction C11 effective 11:45 changes only service to priority. "
                "Quoted old correction Q11 says Greece; unsigned email U08 removes "
                "signature; voided duplicate scan S10 says Austria, express. Signed "
                "correction C12 effective 12:15 changes only destination to France."
            ),
            expected={
                "shipment_id": "SH-777",
                "destination_country": "France",
                "service": "express",
                "declared_value_usd": 1700,
                "signature_required": True,
                "source_by_field": {
                    "destination_country": "C12",
                    "service": "C13",
                    "declared_value_usd": "C14",
                    "signature_required": "C10",
                },
                "discarded_source_ids": [
                    "P02",
                    "P05",
                    "P09",
                    "Q03",
                    "Q07",
                    "Q11",
                    "S06",
                    "S09",
                    "S10",
                    "U01",
                    "U04",
                    "U08",
                ],
                "discarded_source_checksum": 4126617,
            },
        ),
    ),
    scorer=CodeScorer(shipment_matches),
)


if __name__ == "__main__":
    results = run_rollouts(environment, k=6, concurrency=6)
    print(results)
    for task_result in results.task_results:
        print(f"{task_result.task.id}: {task_result.n_passed}/{task_result.n_scored}")
