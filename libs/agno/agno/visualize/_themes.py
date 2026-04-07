"""Predefined color palettes for Mermaid diagrams."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Color flavors — predefined palettes for diagram styling
# ---------------------------------------------------------------------------
COLOR_FLAVORS: dict[str, list[str]] = {
    "default": [
        "classDef stepStyle fill:#e1f5fe,stroke:#0288d1,stroke-width:2px,color:#01579b",
        "classDef conditionStyle fill:#fff8e1,stroke:#f9a825,stroke-width:2px,color:#f57f17",
        "classDef routerStyle fill:#fce4ec,stroke:#c62828,stroke-width:2px,color:#b71c1c",
        "classDef loopStyle fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px,color:#1b5e20",
        "classDef parallelStyle fill:#ede7f6,stroke:#4527a0,stroke-width:2px,color:#311b92",
        "classDef stepsStyle fill:#e0f2f1,stroke:#00695c,stroke-width:2px,color:#004d40",
        "classDef callableStyle fill:#f3e5f5,stroke:#6a1b9a,stroke-width:2px,color:#4a148c",
        "classDef startEnd fill:#e8eaf6,stroke:#283593,stroke-width:2px,color:#1a237e",
    ],
    "monotone": [
        "classDef stepStyle fill:#f5f5f5,stroke:#616161,stroke-width:2px,color:#212121",
        "classDef conditionStyle fill:#eeeeee,stroke:#757575,stroke-width:2px,color:#212121",
        "classDef routerStyle fill:#e0e0e0,stroke:#757575,stroke-width:2px,color:#212121",
        "classDef loopStyle fill:#f5f5f5,stroke:#616161,stroke-width:2px,color:#212121",
        "classDef parallelStyle fill:#eeeeee,stroke:#757575,stroke-width:2px,color:#212121",
        "classDef stepsStyle fill:#fafafa,stroke:#9e9e9e,stroke-width:2px,color:#212121",
        "classDef callableStyle fill:#e0e0e0,stroke:#616161,stroke-width:2px,color:#212121",
        "classDef startEnd fill:#bdbdbd,stroke:#424242,stroke-width:2px,color:#212121",
    ],
    "black": [
        "classDef stepStyle fill:#263238,stroke:#546e7a,stroke-width:2px,color:#eceff1",
        "classDef conditionStyle fill:#1a1a2e,stroke:#e94560,stroke-width:2px,color:#eceff1",
        "classDef routerStyle fill:#16213e,stroke:#e94560,stroke-width:2px,color:#eceff1",
        "classDef loopStyle fill:#0f3460,stroke:#53a8b6,stroke-width:2px,color:#eceff1",
        "classDef parallelStyle fill:#1a1a2e,stroke:#7f5af0,stroke-width:2px,color:#eceff1",
        "classDef stepsStyle fill:#1e272e,stroke:#546e7a,stroke-width:2px,color:#eceff1",
        "classDef callableStyle fill:#2d132c,stroke:#c56cf0,stroke-width:2px,color:#eceff1",
        "classDef startEnd fill:#0a0a0a,stroke:#e0e0e0,stroke-width:2px,color:#eceff1",
    ],
}

AVAILABLE_FLAVORS = list(COLOR_FLAVORS.keys())
