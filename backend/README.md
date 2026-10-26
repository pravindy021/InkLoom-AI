# InkLoom AI backend

FastAPI API for brand guidelines, approved evidence, content analysis, collaborative human review, activity history, and analytics. Local deterministic rules are the default. An optional OpenAI-compatible text model can add advisory findings when explicitly configured.

## Requirements and setup

Python 3.9+ is supported by this implementation.

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Swagger UI is available at `http://localhost:8000/docs`, with OpenAPI JSON at `/openapi.json`. SQLite is created in the backend working directory by default. Configure its location using `DATABASE_URL`.

## Configuration

- `DATABASE_URL`: SQLAlchemy database URL; defaults to `sqlite:///./inkloom.db`.
- `CORS_ORIGINS`: comma-separated explicit frontend origins; defaults to local Vite origins.
- `MAX_CONTENT_LENGTH`: maximum UTF-8 text body size in bytes (default 100,000).
- `MAX_UPLOAD_SIZE`: maximum image upload size in bytes (default 10 MiB).
- `MAX_SOURCE_UPLOAD_SIZE`: maximum source-document upload size in bytes (default 10 MiB).
- `MAX_SOURCE_LENGTH`: maximum extracted source text size in bytes (default 200,000).
- `MAX_IMAGE_PIXELS`: image dimension guard (default 40 million pixels).
- `OCR_ENABLED`: `true` to attempt OCR. `pytesseract` is installed from requirements, but the Tesseract executable must also be installed on the host (for example, `brew install tesseract` on macOS). OCR failures are reported in `image_analysis.limitations`.
- `BRAND_PALETTE`: optional comma-separated approved hex colours, e.g. `#17213A,#665BB8`.
- `PALETTE_TOLERANCE`: approximate RGB distance threshold for the visual palette heuristic (default 36).
- `LLM_API_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`: configure all three to enable the optional OpenAI-compatible `/chat/completions` provider. Leave all empty for local rules only. The configured provider receives submitted content and guideline context; assess its data handling before enabling it.

Uploaded images are validated and processed in memory and are not persisted. OCR text and findings are persisted as review data. Do not send confidential material to a remote LLM unless your deployment and provider data handling have been reviewed. This MVP does not implement authentication, authorization, encryption at rest, or a retention policy.

## API

All endpoints are under `/api`; FastAPI provides interactive schemas at `/docs`.

### Health and guidelines

- `GET /api/health` → `{"status":"ok","version":"1.0.0"}`.
- `GET /api/guidelines` → guideline array. Three starter rules are inserted when the database is first initialized.
- `POST /api/guidelines` → `201` and the created guideline. Required: `name`, `category`, `description`; optional: `severity`, `prohibited_terms`, `preferred_terms`, `approved_sources`.
- `DELETE /api/guidelines/{guideline_id}` → `204`; `404` if not found.
- `GET /api/sources` → approved source text records.
- `POST /api/sources` → `201` approved source text with optional guideline, URL, source date and expiry date.
- `POST /api/sources/upload` → `201`; extracts UTF-8 TXT/Markdown or text-bearing PDF to approved source text (10 MiB and 100-page defaults).
- `DELETE /api/sources/{source_id}` → `204`.

Example create body:

```json
{
  "name": "Preferred product terms",
  "category": "terminology",
  "description": "Use approved product naming.",
  "severity": "medium",
  "prohibited_terms": ["world class"],
  "preferred_terms": ["excellent"],
  "approved_sources": []
}
```

Approved guideline references accept `name`, optional `url`/`reference`, `source_date`, and `expiry_date` (ISO dates). Evidence-library records can be created as JSON text or uploaded with TXT/Markdown/PDF extraction.

### Analysis

`POST /api/analyze` accepts JSON or `multipart/form-data`. JSON fields: `content` (required), `content_type` (default `text`), `title`, `guideline_ids`, `source_ids`, and `alt_text`. Multipart accepts the same fields plus an optional PNG/JPEG/WEBP `file` image and JSON-encoded ID arrays.

```json
{
  "content": "Our product guarantees 100% success for every customer.",
  "content_type": "text",
  "title": "Product campaign",
  "guideline_ids": [],
  "source_ids": []
}
```

The `200` response has a persisted review `id`/`review_id`, `overall_status`, `total_issues`, grouped `summary`, `findings` (also available as `issues`), `analyzed_at`, and optional `image_analysis`. Findings include `category`, `severity`, `title`, `explanation`/`message`, `matched_text`, `suggestion`, `source`/`guideline`, confidence, and pending review status. No-issue analyses are still recorded for human workflow.

The deterministic rules identify configured prohibited terms, selected promotional-claim heuristics, simple factual-looking excerpts, and basic accessibility signals. Lexical source retrieval reports candidate excerpts, source dates, expiry dates, and rough term-overlap relevance. Candidate matches are never treated as proof or marked verified. If the LLM is explicitly configured, validated structured advisory findings are added to the local rules output; provider failures return `502` instead of silently falling back.

Image analysis validates format, size, dimensions, and image integrity, reports dominant colours and checks them against an optional configured palette using approximate Euclidean RGB distance. This is not a perceptually uniform colour comparison. If OCR is enabled and the host Tesseract binary is available, extracted text is checked against the text rules. Logo geometry, layout/object-boundary analysis, and visual-similarity checks are not implemented.

### Review workflow

- `GET /api/reviews?offset=0&limit=20&status=pending` → paginated `{items,total,offset,limit}`.
- `GET /api/reviews/{review_id}` → review with findings, comments, revisions.
- `GET /api/reviews/{review_id}/activity` → append-only application events for analysis, comments, revisions, and status changes.
- `PATCH /api/reviews/{review_id}/status` with `{"status":"in_review","reviewer":"Reviewer Name"}` → updated review; status audit event is persisted.
- `POST /api/reviews/{review_id}/comments` with `{"comment":"Please verify the source.","author":"Reviewer Name"}` → `201` comment.
- `POST /api/reviews/{review_id}/revisions` with `{"content":"Updated draft","title":"Revision 1"}` → `201` revision.

Supported statuses are `pending`, `in_review`, `approved`, and `changes_requested`. Reviewer identity is optional and is not authenticated.

`WS /api/reviews/{review_id}/collaboration` provides process-local presence/typing events, ephemeral shared draft text, and broadcasts newly posted comments, status changes, and revisions. Send JSON `{"type":"typing","user":"Reviewer","active":true}`, `{"type":"presence","user":"Reviewer","active":true}`, or `{"type":"draft_changed","user":"Reviewer","content":"A shared draft"}`. Draft updates are transient until saved using the revision endpoint. Persisted comments continue to use the comments endpoint. Connections and presence are in memory and are not shared across multiple workers/instances. The activity log is append-only through this API, but is not cryptographically immutable.

### Analytics

- `GET /api/analytics/summary` aggregates stored reviews/findings by status, category, severity, and guideline.
- `GET /api/analytics/guideline-blind-spots` returns frequency indicators for triggered guidelines. `ambiguity_score` is normalized trigger frequency only; it is explicitly not proof of ambiguity.

## Deliberate MVP boundaries

This backend does not implement OAuth/JWT, role authorization, encryption-at-rest guarantees, private model hosting, vector database/semantic RAG, live external fact-checking, Figma/Slack/Docs/CMS integrations, CMS publishing, distributed worker pools, Temporal workflows, or cryptographically tamper-proof audit storage. WebSocket collaboration is lightweight and single-process. Configure those services and complete a security review before production use.

## Tests

```bash
pytest
```

Tests use an in-memory SQLite database and do not change the development database.
