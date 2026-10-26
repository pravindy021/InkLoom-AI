from io import BytesIO
import math
from pathlib import Path
from typing import Any, Dict, Optional

from PIL import Image, ImageFilter, UnidentifiedImageError

from app.config import (
    BRAND_ASSET_REFERENCES,
    BRAND_ASSET_SIMILARITY_THRESHOLD,
    BRAND_PALETTE,
    MAX_IMAGE_PIXELS,
    MAX_UPLOAD_SIZE,
    PALETTE_TOLERANCE,
)

SUPPORTED_FORMATS = {"PNG", "JPEG", "WEBP"}


class ImageAnalysisConfigurationError(RuntimeError):
    pass


def _difference_hash(image: Image.Image) -> int:
    pixels = list(
        image.convert("L")
        .resize((9, 8), Image.Resampling.LANCZOS)
        .getdata()
    )
    result = 0
    for row in range(8):
        for column in range(8):
            result = (result << 1) | int(
                pixels[row * 9 + column] > pixels[row * 9 + column + 1]
            )
    return result


def _layout_metrics(image: Image.Image) -> Dict[str, Any]:
    width, height = image.size
    ratio = width / height
    if ratio > 1.1:
        orientation = "landscape"
    elif ratio < 0.9:
        orientation = "portrait"
    else:
        orientation = "near_square"

    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    alpha_min, alpha_max = alpha.getextrema()
    transparent_bounds = None
    if alpha_min < 255:
        content_box = alpha.point(lambda value: 255 if value > 16 else 0).getbbox()
        if content_box:
            left, top, right, bottom = content_box
            content_width = right - left
            content_height = bottom - top
            transparent_bounds = {
                "left_margin_percent": round(left / width * 100, 1),
                "top_margin_percent": round(top / height * 100, 1),
                "right_margin_percent": round((width - right) / width * 100, 1),
                "bottom_margin_percent": round((height - bottom) / height * 100, 1),
                "content_occupancy_percent": round(
                    content_width * content_height / (width * height) * 100, 1
                ),
            }

    edges = (
        image.convert("L")
        .resize((128, 128), Image.Resampling.LANCZOS)
        .filter(ImageFilter.FIND_EDGES)
    )
    edge_pixels = list(edges.getdata())
    edge_density = sum(value >= 32 for value in edge_pixels) / len(edge_pixels)
    return {
        "orientation": orientation,
        "aspect_ratio": round(ratio, 3),
        "has_transparency": alpha_min < 255 or alpha_max < 255,
        "transparent_bounds": transparent_bounds,
        "edge_density_percent": round(edge_density * 100, 1),
        "small_for_large_display": max(width, height) < 500,
        "method": "Image geometry and grayscale edge-density heuristics; not a layout or accessibility audit.",
    }


def _reference_image_similarity(image: Image.Image) -> Dict[str, Any]:
    if not BRAND_ASSET_REFERENCES:
        return {
            "configured": False,
            "references": [],
            "threshold_percent": BRAND_ASSET_SIMILARITY_THRESHOLD,
            "potential_mismatch": None,
        }

    uploaded_hash = _difference_hash(image)
    comparisons = []
    for reference_path in BRAND_ASSET_REFERENCES:
        path = Path(reference_path).expanduser()
        try:
            if not path.is_file() or path.stat().st_size > MAX_UPLOAD_SIZE:
                raise OSError("Reference file is missing or exceeds the size limit.")
            with Image.open(path) as reference:
                if reference.format not in SUPPORTED_FORMATS:
                    raise OSError("Reference image format is unsupported.")
                if reference.width * reference.height > MAX_IMAGE_PIXELS:
                    raise OSError("Reference image exceeds the pixel limit.")
                reference.load()
                distance = bin(uploaded_hash ^ _difference_hash(reference)).count("1")
        except (OSError, UnidentifiedImageError, ValueError, Image.DecompressionBombError) as exc:
            raise ImageAnalysisConfigurationError(
                "A configured brand asset reference could not be read or validated."
            ) from exc
        similarity_percent = round((64 - distance) / 64 * 100)
        comparisons.append(
            {
                "name": path.name,
                "similarity_percent": similarity_percent,
                "method": "64-bit difference hash; coarse visual similarity only",
            }
        )
    best_match = max(item["similarity_percent"] for item in comparisons)
    return {
        "configured": True,
        "references": comparisons,
        "threshold_percent": BRAND_ASSET_SIMILARITY_THRESHOLD,
        "potential_mismatch": best_match < BRAND_ASSET_SIMILARITY_THRESHOLD,
    }


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
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("The uploaded file is not a valid supported image.") from exc

    if image_format not in SUPPORTED_FORMATS:
        raise ValueError("Only PNG, JPEG, and WEBP images are supported.")

    with Image.open(BytesIO(image_bytes)) as image:
        layout_metrics = _layout_metrics(image)
        reference_similarity = _reference_image_similarity(image)
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
        "layout_metrics": layout_metrics,
        "brand_asset_similarity": reference_similarity,
        "dominant_colors": dominant_colors,
        "palette_comparison": palette_comparison,
        "extracted_text": None,
        "ocr_available": False,
        "limitations": limitations
        + [
            "Element alignment, logo safe-zone compliance, and semantic visual understanding are not checked."
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
