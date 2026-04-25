"""Load intent routing rules for the system prompt."""

import json
from pathlib import Path
from typing import Any

from agno.utils.log import logger

from ..paths import ROUTING_DIR


def load_intent_rules(routing_dir: Path | None = None) -> dict[str, Any]:
    """Load intent routing rules from JSON files."""
    if routing_dir is None:
        routing_dir = ROUTING_DIR

    rules: dict[str, Any] = {
        "intent_mappings": [],
        "source_preferences": [],
        "common_gotchas": [],
    }

    if not routing_dir.exists():
        return rules

    for filepath in sorted(routing_dir.glob("*.json")):
        try:
            with open(filepath) as f:
                data = json.load(f)
            for key in rules:
                if key in data:
                    rules[key].extend(data[key])
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to load {filepath}: {e}")

    return rules


def build_intent_routing(routing_dir: Path | None = None) -> str:
    """Build intent routing context string for system prompt."""
    rules = load_intent_rules(routing_dir)
    lines: list[str] = []

    # Intent mappings
    if rules["intent_mappings"]:
        lines.append("## INTENT ROUTING\n")
        lines.append("When the user asks about:")
        lines.append("")
        for mapping in rules["intent_mappings"]:
            intent = mapping.get("intent", "Unknown")
            primary = mapping.get("primary_source", "unknown")
            fallbacks = mapping.get("fallback_sources", [])
            reasoning = mapping.get("reasoning", "")

            lines.append(f"**{intent}**")
            lines.append(f"  - Primary: `{primary}`")
            if fallbacks:
                lines.append(f"  - Fallback: {', '.join(f'`{f}`' for f in fallbacks)}")
            if reasoning:
                lines.append(f"  - Why: {reasoning}")
            lines.append("")

    # Source preferences
    if rules["source_preferences"]:
        lines.append("## SOURCE STRENGTHS\n")
        for pref in rules["source_preferences"]:
            source = pref.get("source", "Unknown")
            best_for = pref.get("best_for", [])
            search_first = pref.get("search_first_when", [])

            lines.append(f"**{source}**")
            if best_for:
                lines.append(f"  - Best for: {', '.join(best_for)}")
            if search_first:
                lines.append(f"  - Search first when: {'; '.join(search_first)}")
            lines.append("")

    # Common gotchas
    if rules["common_gotchas"]:
        lines.append("## COMMON GOTCHAS\n")
        for gotcha in rules["common_gotchas"]:
            issue = gotcha.get("issue", "Unknown")
            description = gotcha.get("description", "")
            solution = gotcha.get("solution", "")

            lines.append(f"**{issue}**")
            if description:
                lines.append(f"  - {description}")
            if solution:
                lines.append(f"  - Solution: {solution}")
            lines.append("")

    return "\n".join(lines)


INTENT_ROUTING = load_intent_rules()
INTENT_ROUTING_CONTEXT = build_intent_routing()
