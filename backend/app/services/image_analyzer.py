from io import BytesIO
import math
from typing import Any, Dict, Optional

from PIL import Image, UnidentifiedImageError

from app.config import BRAND_PALETTE, MAX_IMAGE_PIXELS, PALETTE_TOLERANCE

SUPPORTED_FORMATS = {"PNG", "JPEG", "WEBP"}


def inspect_image(image_bytes: bytes, ocr_enabled: bool = False) -> Dict[str, Any]:
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image_format = image.format
            width, height = image.size
            if width * height > MAX_IMAGE_PIXELS:
                raise ValueError("Image dimensions exceed the configured pixel limit.")
            image.verify()
    except ValueError as exc:
        if "pixel limit" in str(exc):
            raise
        raise ValueError("The uploaded file is not a valid supported image.") from exc
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("The uploaded file is not a valid supported image.") from exc

    if image_format not in SUPPORTED_FORMATS:
        raise ValueError("Only PNG, JPEG, and WEBP images are supported.")

    with Image.open(BytesIO(image_bytes)) as image:
        quantized = image.convert("RGB").resize((256, 256)).quantize(colors=5)
        palette = quantized.getpalette() or []
        color_counts = sorted(quantized.getcolors(256 * 256) or [], reverse=True)
        dominant_colors = []
        for count, palette_index in color_counts[:5]:
            start = palette_index * 3
            rgb = palette[start : start + 3]
            if len(rgb) == 3:
                dominant_colors.append(
                    {"hex": "#{:02X}{:02X}{:02X}".format(*rgb), "pixel_share": round(count / (256 * 256), 3)}
                )

    configured_colors = []
    for color in BRAND_PALETTE:
        normalized = color.lstrip("#")
        if len(normalized) == 6:
            try:
                configured_colors.append(
                    tuple(int(normalized[index : index + 2], 16) for index in (0, 2, 4))
                )
            except ValueError:
                continue

    palette_comparison = None
    limitations = []
    if configured_colors:
        comparisons = []
        for color in dominant_colors:
            image_rgb = tuple(
                int(color["hex"][index : index + 2], 16) for index in (1, 3, 5)
            )
            nearest_distance = min(
                math.sqrt(sum((actual - expected) ** 2 for actual, expected in zip(image_rgb, reference)))
                for reference in configured_colors
            )
            comparisons.append(
                {
                    "image_color": color["hex"],
                    "nearest_brand_color_distance": round(nearest_distance, 1),
                    "within_tolerance": nearest_distance <= PALETTE_TOLERANCE,
                }
            )
        palette_comparison = {
            "method": "Euclidean RGB distance approximation; not perceptually uniform",
            "tolerance": PALETTE_TOLERANCE,
            "colors": comparisons,
            "potential_mismatch": any(not item["within_tolerance"] for item in comparisons),
        }
    else:
        limitations.append(
            "No approved brand palette is configured; image colours were measured but not evaluated for brand compliance."
        )

    result: Dict[str, Any] = {
        "format": image_format.lower(),
        "width": width,
        "height": height,
        "dominant_colors": dominant_colors,
        "palette_comparison": palette_comparison,
        "extracted_text": None,
        "ocr_available": False,
        "limitations": limitations
        + [
            "Logo geometry, layout alignment, and visual similarity were not checked because reference assets and comparison models are not configured."
        ],
    }
    if not ocr_enabled:
        result["limitations"].append("OCR is disabled; text embedded in the image was not analyzed.")
        return result

    try:
        import pytesseract
    except ImportError:
        result["limitations"].append(
            "OCR was requested but pytesseract is not installed; extracted image text was not analyzed."
        )
        return result

    try:
        with Image.open(BytesIO(image_bytes)) as image:
            result["extracted_text"] = pytesseract.image_to_string(image).strip()
        result["ocr_available"] = True
    except (pytesseract.TesseractNotFoundError, pytesseract.TesseractError, OSError) as exc:
        result["limitations"].append(
            "OCR could not process this image; extracted image text was not analyzed ({0}).".format(
                type(exc).__name__
            )
        )
    return result
