"""Load business definitions, metrics, and common gotchas."""

import json
from pathlib import Path
from typing import Any

from agno.utils.log import logger

from ..paths import BUSINESS_DIR


def load_business_rules(business_dir: Path | None = None) -> dict[str, list[Any]]:
    """Load business definitions from JSON files."""
    if business_dir is None:
        business_dir = BUSINESS_DIR

    business: dict[str, list[Any]] = {
        "metrics": [],
        "business_rules": [],
        "common_gotchas": [],
    }

    if not business_dir.exists():
        return business

    for filepath in sorted(business_dir.glob("*.json")):
        try:
            with open(filepath) as f:
                data = json.load(f)
            for key in business:
                if key in data:
                    business[key].extend(data[key])
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to load {filepath}: {e}")

    return business


def build_business_context(business_dir: Path | None = None) -> str:
    """Build business context string for system prompt."""
    business = load_business_rules(business_dir)
    lines: list[str] = []

    if business["metrics"]:
        lines.append("## METRICS\n")
        for m in business["metrics"]:
            lines.append(f"**{m.get('name', 'Unknown')}**: {m.get('definition', '')}")
            if m.get("table"):
                lines.append(f"  - Table: `{m['table']}`")
            if m.get("calculation"):
                lines.append(f"  - Calculation: {m['calculation']}")
            lines.append("")

    if business["business_rules"]:
        lines.append("## BUSINESS RULES\n")
        for rule in business["business_rules"]:
            lines.append(f"- {rule}")
        lines.append("")

    if business["common_gotchas"]:
        lines.append("## COMMON GOTCHAS\n")
        for g in business["common_gotchas"]:
            lines.append(f"**{g.get('issue', 'Unknown')}**")
            if g.get("tables_affected"):
                lines.append(f"  - Tables: {', '.join(g['tables_affected'])}")
            if g.get("solution"):
                lines.append(f"  - Solution: {g['solution']}")
            lines.append("")

    return "\n".join(lines)


BUSINESS_CONTEXT = build_business_context()
