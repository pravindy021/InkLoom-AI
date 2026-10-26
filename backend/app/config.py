import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

BACKEND_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_environment(env_file: Path = BACKEND_ENV_FILE) -> bool:
    return load_dotenv(dotenv_path=env_file, override=False)


load_environment()


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
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "").strip()
FACT_CHECK_PROVIDER = os.getenv("FACT_CHECK_PROVIDER", "").strip().lower()
FACT_CHECK_API_KEY = os.getenv("FACT_CHECK_API_KEY", "").strip()
TRUSTED_SOURCE_DOMAINS = tuple(
    domain.strip().lower().rstrip(".")
    for domain in os.getenv("TRUSTED_SOURCE_DOMAINS", "").split(",")
    if domain.strip()
)
if FACT_CHECK_PROVIDER not in {"", "brave"}:
    raise ValueError("FACT_CHECK_PROVIDER must be empty or 'brave'.")
if bool(FACT_CHECK_PROVIDER) != bool(FACT_CHECK_API_KEY):
    raise ValueError("Configure FACT_CHECK_PROVIDER and FACT_CHECK_API_KEY together.")
if any(
    not re.fullmatch(
        r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}",
        domain,
    )
    for domain in TRUSTED_SOURCE_DOMAINS
):
    raise ValueError("TRUSTED_SOURCE_DOMAINS must contain bare DNS domain names.")
FACT_CHECK_ENABLED = bool(FACT_CHECK_PROVIDER and TRUSTED_SOURCE_DOMAINS)
BRAND_PALETTE = [
    color.strip().upper()
    for color in os.getenv("BRAND_PALETTE", "").split(",")
    if color.strip()
]
PALETTE_TOLERANCE = _integer_setting("PALETTE_TOLERANCE", 36, 0)
MAX_IMAGE_PIXELS = _integer_setting("MAX_IMAGE_PIXELS", 40_000_000, 1)
BRAND_ASSET_REFERENCES = [
    path.strip()
    for path in os.getenv("BRAND_ASSET_REFERENCE_PATHS", "").split(",")
    if path.strip()
]
BRAND_ASSET_SIMILARITY_THRESHOLD = _integer_setting(
    "BRAND_ASSET_SIMILARITY_THRESHOLD", 72, 0
)
if len(BRAND_ASSET_REFERENCES) > 5:
    raise ValueError("Configure no more than five BRAND_ASSET_REFERENCE_PATHS.")
if BRAND_ASSET_SIMILARITY_THRESHOLD > 100:
    raise ValueError("BRAND_ASSET_SIMILARITY_THRESHOLD must be between 0 and 100.")
if PALETTE_TOLERANCE > 441:
    raise ValueError("PALETTE_TOLERANCE must be between 0 and 441.")
if any(not re.fullmatch(r"#?[0-9A-Fa-f]{6}", color) for color in BRAND_PALETTE):
    raise ValueError("BRAND_PALETTE entries must be six-digit hex colours.")
_llm_settings = [
    os.getenv("LLM_API_BASE_URL", "").strip(),
    os.getenv("LLM_API_KEY", "").strip(),
    os.getenv("LLM_MODEL", "").strip(),
]
if LLM_MODEL and not all(_llm_settings):
    raise ValueError(
        "LLM_MODEL requires LLM_API_BASE_URL and LLM_API_KEY."
    )
if bool(LLM_API_BASE_URL) != bool(LLM_API_KEY):
    raise ValueError("Configure LLM_API_BASE_URL and LLM_API_KEY together.")
if EMBEDDING_MODEL and not (LLM_API_BASE_URL and LLM_API_KEY):
    raise ValueError(
        "EMBEDDING_MODEL requires LLM_API_BASE_URL and LLM_API_KEY."
    )
if (LLM_API_BASE_URL or LLM_API_KEY) and not (LLM_MODEL or EMBEDDING_MODEL):
    raise ValueError("Configure LLM_MODEL or EMBEDDING_MODEL to use the provider.")
LLM_ENABLED = bool(LLM_MODEL)
EMBEDDINGS_ENABLED = bool(EMBEDDING_MODEL)
MAX_RETRIEVAL_CHUNKS = _integer_setting("MAX_RETRIEVAL_CHUNKS", 200, 1)
BOOTSTRAP_ADMIN_EMAIL = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
BOOTSTRAP_ADMIN_PASSWORD = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
AUTH_COOKIE_NAME = "inkloom_session"
AUTH_COOKIE_SECURE = os.getenv("AUTH_COOKIE_SECURE", "false").lower() == "true"
AUTH_SESSION_HOURS = _integer_setting("AUTH_SESSION_HOURS", 12, 1)
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = _integer_setting("SMTP_PORT", 587, 1)
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "").strip()
SMTP_STARTTLS = os.getenv("SMTP_STARTTLS", "true").lower() == "true"
SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "false").lower() == "true"
PASSWORD_RESET_BASE_URL = os.getenv(
    "PASSWORD_RESET_BASE_URL", "http://localhost:5173"
).rstrip("/")
SMTP_ENABLED = bool(SMTP_HOST and SMTP_FROM_EMAIL)
if bool(SMTP_USERNAME) != bool(SMTP_PASSWORD):
    raise ValueError("Configure SMTP_USERNAME and SMTP_PASSWORD together.")
if bool(SMTP_HOST) != bool(SMTP_FROM_EMAIL):
    raise ValueError("Configure SMTP_HOST and SMTP_FROM_EMAIL together.")
if SMTP_STARTTLS and SMTP_USE_SSL:
    raise ValueError("Use either SMTP_STARTTLS or SMTP_USE_SSL, not both.")
if SMTP_HOST and not (SMTP_STARTTLS or SMTP_USE_SSL):
    raise ValueError("SMTP must use STARTTLS or implicit TLS.")
if SMTP_PORT > 65535:
    raise ValueError("SMTP_PORT must not exceed 65535.")
if SMTP_FROM_EMAIL and (
    len(SMTP_FROM_EMAIL) > 254
    or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", SMTP_FROM_EMAIL)
):
    raise ValueError("SMTP_FROM_EMAIL must be a valid email address.")
_password_reset_url = urlsplit(PASSWORD_RESET_BASE_URL)
if (
    _password_reset_url.scheme not in {"http", "https"}
    or not _password_reset_url.netloc
    or _password_reset_url.username
    or _password_reset_url.password
    or _password_reset_url.query
    or _password_reset_url.fragment
):
    raise ValueError(
        "PASSWORD_RESET_BASE_URL must be an HTTP or HTTPS URL without credentials, query, or fragment."
    )
if bool(BOOTSTRAP_ADMIN_EMAIL) != bool(BOOTSTRAP_ADMIN_PASSWORD):
    raise ValueError(
        "Configure BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD together."
    )
if BOOTSTRAP_ADMIN_PASSWORD and len(BOOTSTRAP_ADMIN_PASSWORD) < 12:
    raise ValueError("BOOTSTRAP_ADMIN_PASSWORD must contain at least 12 characters.")
if BOOTSTRAP_ADMIN_EMAIL and (
    len(BOOTSTRAP_ADMIN_EMAIL) > 254
    or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", BOOTSTRAP_ADMIN_EMAIL)
):
    raise ValueError("BOOTSTRAP_ADMIN_EMAIL must be a valid email address.")
if AUTH_SESSION_HOURS > 720:
    raise ValueError("AUTH_SESSION_HOURS cannot exceed 720 hours.")
API_VERSION = "1.0.0"
