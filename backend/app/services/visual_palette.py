import re
from typing import Any, Dict, Iterable, Optional

from sqlalchemy.orm import Session

from app.models.visual_brand import VisualBrandConfiguration
from app.services import image_analyzer

_HEX_COLOR = re.compile(r"(?<![0-9A-Fa-f])#?([0-9A-Fa-f]{6})(?![0-9A-Fa-f])")
VISUAL_CATEGORIES = {
    "visual",
    "visual_brand",
    "visual_identity",
    "brand_color",
    "brand_colour",
    "brand_colors",
    "brand_colours",
    "logo",
    "accessibility",
}


def _normalized_category(value: Optional[str]) -> str:
    return (value or "").strip().lower().replace("-", "_").replace(" ", "_")


def is_visual_category(value: Optional[str]) -> bool:
    return _normalized_category(value) in VISUAL_CATEGORIES


def guideline_palette_colors(guidelines: Iterable[Any]) -> list[Dict[str, Any]]:
    colors = []
    for guideline in guidelines:
        if not is_visual_category(guideline.category):
            continue
        text = " ".join(
            [
                guideline.name or "",
                guideline.description or "",
                " ".join(guideline.examples or []),
            ]
        )
        for match in _HEX_COLOR.finditer(text):
            color = "#" + match.group(1).upper()
            if not any(item["color"] == color for item in colors):
                colors.append(
                    {
                        "color": color,
                        "guideline_id": guideline.id,
                        "guideline": guideline.name,
                    }
                )
    return colors


def resolve_visual_palette(
    db: Optional[Session],
    guidelines: Iterable[Any],
) -> Dict[str, Any]:
    """Prefer saved colors over environment colors; keep guideline colors additive."""
    saved = db.get(VisualBrandConfiguration, 1) if db is not None else None
    guideline_colors = guideline_palette_colors(guidelines)

    if saved is not None:
        source = "saved"
        selected_colors = [
            {"color": color, "role": role}
            for role in ("primary", "secondary", "accent")
            for color in (getattr(saved, role) or [])
        ]
    else:
        environment_colors = image_analyzer.BRAND_PALETTE
        source = (
            "environment"
            if environment_colors
            else "guidelines"
            if guideline_colors
            else "none"
        )
        selected_colors = [
            {"color": color.upper(), "role": "environment"}
            for color in environment_colors
        ]

    seen = {item["color"] for item in selected_colors}
    for item in guideline_colors:
        if item["color"] not in seen:
            selected_colors.append(
                {
                    "color": item["color"],
                    "role": "guideline",
                    "guideline_id": item["guideline_id"],
                    "guideline": item["guideline"],
                }
            )
            seen.add(item["color"])

    return {
        "source": source,
        "configured": bool(selected_colors),
        "colors": selected_colors,
        "guideline_colors_included": bool(guideline_colors),
        "tolerance": image_analyzer.PALETTE_TOLERANCE,
        "method": "Euclidean RGB distance approximation; not perceptually uniform",
    }
