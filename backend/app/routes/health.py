from fastapi import APIRouter

from app.config import API_VERSION
from app.config import BRAND_PALETTE, OCR_ENABLED, PALETTE_TOLERANCE
from app.services.llm_analyzer import llm_enabled

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health():
    return {
        "status": "ok",
        "version": API_VERSION,
        "analysis_mode": "rules+configured_llm" if llm_enabled() else "rules",
        "ocr_enabled": OCR_ENABLED,
        "brand_palette_configured": bool(BRAND_PALETTE),
        "palette_tolerance": PALETTE_TOLERANCE if BRAND_PALETTE else None,
        "brand_palette": BRAND_PALETTE,
        "collaboration": "websocket_process_local",
    }
