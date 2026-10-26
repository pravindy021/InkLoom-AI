import os
import re

from dotenv import load_dotenv

load_dotenv()


def _integer_setting(name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./inkloom.db")
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if origin.strip()
]
MAX_CONTENT_LENGTH = _integer_setting("MAX_CONTENT_LENGTH", 100_000, 1)
MAX_UPLOAD_SIZE = _integer_setting("MAX_UPLOAD_SIZE", 10 * 1024 * 1024, 1)
MAX_SOURCE_UPLOAD_SIZE = _integer_setting("MAX_SOURCE_UPLOAD_SIZE", 10 * 1024 * 1024, 1)
MAX_SOURCE_LENGTH = _integer_setting("MAX_SOURCE_LENGTH", 200_000, 1)
OCR_ENABLED = os.getenv("OCR_ENABLED", "false").lower() == "true"
LLM_API_BASE_URL = os.getenv("LLM_API_BASE_URL", "").rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "")
BRAND_PALETTE = [
    color.strip().upper()
    for color in os.getenv("BRAND_PALETTE", "").split(",")
    if color.strip()
]
PALETTE_TOLERANCE = _integer_setting("PALETTE_TOLERANCE", 36, 0)
MAX_IMAGE_PIXELS = _integer_setting("MAX_IMAGE_PIXELS", 40_000_000, 1)
if PALETTE_TOLERANCE > 441:
    raise ValueError("PALETTE_TOLERANCE must be between 0 and 441.")
if any(not re.fullmatch(r"#?[0-9A-Fa-f]{6}", color) for color in BRAND_PALETTE):
    raise ValueError("BRAND_PALETTE entries must be six-digit hex colours.")
_llm_settings = [
    os.getenv("LLM_API_BASE_URL", "").strip(),
    os.getenv("LLM_API_KEY", "").strip(),
    os.getenv("LLM_MODEL", "").strip(),
]
if any(_llm_settings) and not all(_llm_settings):
    raise ValueError(
        "Configure LLM_API_BASE_URL, LLM_API_KEY, and LLM_MODEL together, or leave all empty."
    )
LLM_ENABLED = all(_llm_settings)
API_VERSION = "1.0.0"
