"""
Search-tuned schema for indexed images.

Every field is designed to contribute distinct signal to the embedded text
that we hand to the vector DB. Together they cover the kinds of phrases
users actually type into image search: a free-form caption, the literal
subjects, the scene, the visual feel, and a denormalized tag bag.
"""

from typing import List

from pydantic import BaseModel, Field


class ImageDescription(BaseModel):
    """Search-tuned description produced by the labeling agent."""

    caption: str = Field(
        ...,
        description=(
            "One or two sentences describing the image in everyday language. "
            "Write it the way a user would type a search query for this image — "
            "concrete nouns, common adjectives, no flowery prose."
        ),
    )

    subjects: List[str] = Field(
        default_factory=list,
        description=(
            "Main subjects in the image: people, animals, objects, vehicles, "
            "named places. 1-5 short noun phrases."
        ),
    )

    scene: str = Field(
        ...,
        description=(
            "Where the image takes place, as a short noun phrase. "
            "Examples: 'mountain valley at sunset', 'urban street at night', "
            "'cozy cafe interior', 'studio still life'."
        ),
    )

    visual_style: str = Field(
        ...,
        description=(
            "One short phrase describing aesthetic, lighting, or composition. "
            "Examples: 'soft morning light', 'dramatic backlight', "
            "'minimalist composition', 'vibrant macro', 'film grain look'."
        ),
    )

    tags: List[str] = Field(
        default_factory=list,
        description=(
            "5-10 short search keywords. Include both literal contents and "
            "conceptual associations (e.g. for a coffee cup also include "
            "'morning', 'cafe', 'breakfast'). Lowercase, single words or "
            "short phrases."
        ),
    )


def to_searchable_text(d: ImageDescription) -> str:
    """Flatten an ImageDescription into a single string for embedding.

    The caption leads (highest-quality semantic signal). Subjects, scene,
    style, and tags follow as structured signal that the embedder can use
    to disambiguate near-neighbors.
    """
    parts = [d.caption.strip()]
    if d.subjects:
        parts.append(f"Subjects: {', '.join(d.subjects)}.")
    parts.append(f"Scene: {d.scene}.")
    parts.append(f"Style: {d.visual_style}.")
    if d.tags:
        parts.append(f"Tags: {', '.join(d.tags)}.")
    return " ".join(parts)
