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
# Set BOOTSTRAP_ADMIN_EMAIL and a unique BOOTSTRAP_ADMIN_PASSWORD in .env before starting.
chmod 600 .env
uvicorn app.main:app --reload
```

Swagger UI is available at `http://localhost:8000/docs`, with OpenAPI JSON at `/openapi.json`. SQLite is created in the backend working directory by default. Configure its location using `DATABASE_URL`.

Authentication is enabled by default. On an empty user database, set `BOOTSTRAP_ADMIN_EMAIL` and a unique `BOOTSTRAP_ADMIN_PASSWORD` of at least 12 characters in `backend/.env`; the first account is created as an administrator at startup. The API loads this file by its path relative to the backend source, independent of the shell's current directory, without overriding environment variables already supplied by the process. Restrict the file to the owner (`chmod 600 .env`); do not commit it or reuse a development password. Bootstrap is intentionally create-only: if any user already exists, it will neither add another bootstrap administrator nor reset an existing account's password. For a database with existing users, sign in with an existing active Admin account. Admins invite accounts from **Admin dashboard → Invite user**; each recipient sets their own password through a single-use email link.

## Configuration

- `DATABASE_URL`: SQLAlchemy database URL; defaults to `sqlite:///./inkloom.db`.
- `CORS_ORIGINS`: comma-separated explicit frontend origins; defaults to local Vite origins.
- `BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ADMIN_PASSWORD`: initial admin account for a new database; both are required together. Bootstrap will not add another admin once any account exists.
- `AUTH_COOKIE_SECURE`: set `true` when served over HTTPS (default `false` for local HTTP development).
- `AUTH_SESSION_HOURS`: absolute session lifetime in hours (default 12).
- Login protection: five failed attempts per email/IP pair, twenty per email, or thirty per IP in a rolling 15-minute window. Blocked requests return `429` with a `Retry-After` header. Failed-attempt identifiers are stored as SHA-256 fingerprints in the configured database. Forwarded IP headers are not trusted by default; configure trusted-proxy handling at the deployment edge before placing the API behind a proxy.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`: configure outbound recovery email. Username/password must be configured together; host and sender are also required together. SMTP requires STARTTLS (`SMTP_STARTTLS=true`, default) or implicit TLS (`SMTP_USE_SSL=true`); plaintext transport is rejected.
- `PASSWORD_RESET_BASE_URL`: frontend origin used to build reset links (default `http://localhost:5173`). Configure the trusted HTTPS frontend origin in deployment; credentials, query strings, and fragments are not accepted.
- Invitation links use the same SMTP and frontend-origin settings as password recovery. They expire after 48 hours. Resending an invitation revokes previous outstanding links.
- `MAX_CONTENT_LENGTH`: maximum UTF-8 text body size in bytes (default 100,000).
- `MAX_UPLOAD_SIZE`: maximum image upload size in bytes (default 10 MiB).
- `MAX_SOURCE_UPLOAD_SIZE`: maximum source-document upload size in bytes (default 10 MiB).
- `MAX_SOURCE_LENGTH`: maximum extracted source text size in bytes (default 200,000).
- `MAX_IMAGE_PIXELS`: image dimension guard (default 40 million pixels).
- `OCR_ENABLED`: `true` to attempt OCR. `pytesseract` is installed from requirements, but the Tesseract executable must also be installed on the host (for example, `brew install tesseract` on macOS). OCR failures are reported in `image_analysis.limitations`.
- `BRAND_PALETTE`: optional comma-separated approved hex colours, e.g. `#17213A,#665BB8`.
- `PALETTE_TOLERANCE`: approximate RGB distance threshold for the visual palette heuristic (default 36).
- `BRAND_ASSET_REFERENCE_PATHS`: optional comma-separated local paths to up to five approved PNG/JPEG/WEBP brand assets. The backend compares uploaded images with these references using a coarse 64-bit difference hash; keep reference files local and restrict filesystem access appropriately.
- `BRAND_ASSET_SIMILARITY_THRESHOLD`: similarity percentage below which the backend emits an advisory that the upload may be a different asset variant (default 72).
- `LLM_API_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`: configure all three to enable the optional OpenAI-compatible `/chat/completions` provider. Leave all empty for local rules only, or configure the URL/key with `EMBEDDING_MODEL` for embedding-only retrieval. The chat provider receives submitted content and guideline context; assess its data handling before enabling it.
- `EMBEDDING_MODEL`: optional OpenAI-compatible `/embeddings` model name. Configure this with `LLM_API_BASE_URL` and `LLM_API_KEY`; it can be enabled without `LLM_MODEL` or LLM analysis. When enabled, factual excerpts and selected approved-source chunks are sent to this provider. Each source chunk embedding is cached in the application database for that model.
- `MAX_RETRIEVAL_CHUNKS`: maximum source chunks considered per analysis (default 200). Text is split into overlapping 1,000-character chunks.
- `FACT_CHECK_PROVIDER`, `FACT_CHECK_API_KEY`, `TRUSTED_SOURCE_DOMAINS`: optional Brave Search integration. Set the provider to `brave`, configure its API key, and provide a comma-separated allowlist of bare domains. External lookup remains off unless the user explicitly opts in on the analysis page; only detected claim excerpts are sent. Search results outside the configured domains are discarded.

Uploaded images are validated and processed in memory and are not persisted. OCR text and findings are persisted as review data. Do not send confidential material to a remote LLM unless your deployment and provider data handling have been reviewed. This MVP does not provide encryption-at-rest guarantees or a retention policy.

Factual verification compares detected numeric and promotional claims with administrator-managed approved source documents. The optional external lookup uses Brave Search only after per-analysis user consent, sends extracted claim text (not the complete draft or image), and only accepts results whose host matches `TRUSTED_SOURCE_DOMAINS`. Provider results are stored as candidate citations with the review. A configured source match is not proof; contradictory/unverified statuses are advisory heuristics, and every publication decision remains with a human reviewer. An external-provider failure leaves the claim unverified and does not block the regular analysis.

### Authentication and roles

- Sessions use opaque random tokens in `HttpOnly`, `SameSite=Strict` cookies; only SHA-256 token digests are stored in the database. Passwords are hashed with PBKDF2-HMAC-SHA256.
- `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`, and `POST /api/auth/password` handle session and password operations.
- Admins can list members, invite accounts, resend pending invitations, and update account roles/status at `/api/auth/users`. Invitation creation and resend require SMTP configuration. Invited accounts remain inactive until a recipient accepts the 48-hour single-use link and sets a password of at least 12 characters; the database stores only the token digest. Invitation links and passwords are never returned by the API or written to application audit records/logs. Account creation, resend, acceptance, and updates create account audit events.
- `POST /api/auth/invitations/accept` accepts `{"token":"...","new_password":"..."}` and activates the account with the role selected by the Admin. Public self-registration is not implemented.
- **Admin** can manage users, guidelines and approved sources, analyze content, and manage reviews.
- **Reviewer** can read guidelines/sources, analyze content, and manage review status, comments, and revisions.
- **Contributor** can read workspace materials, submit analyses, and add comments/revisions; only Admins and Reviewers can decide review status.
- Review author/reviewer names are taken from the signed-in account, not trusted from client-supplied identity fields.
- Authenticated state-changing requests validate their `Origin`; WebSocket collaboration validates both session and origin. Use the same host name for frontend and API in local development, as configured by `CORS_ORIGINS`.

## API

All endpoints are under `/api`; FastAPI provides interactive schemas at `/docs`.

### Health and guidelines

- `GET /api/health` is public and reports service capabilities without secrets.
- `POST /api/auth/login` accepts `{"email":"...","password":"..."}` and sets the session cookie.
- `POST /api/auth/logout` revokes the current session; `GET /api/auth/me` returns the current account.
- `POST /api/auth/password` accepts `current_password` and a `new_password` of at least 12 characters, then rotates the session.
- `POST /api/auth/password/forgot` accepts `{"email":"..."}` and returns the same generic `202` response for existing and unknown accounts. Recovery requests are limited to three per address and ten per IP per hour; only hashed email/IP fingerprints are stored.
- `POST /api/auth/password/reset` accepts `{"token":"...","new_password":"..."}`. A reset token is stored only as a SHA-256 digest, expires after 20 minutes, is single-use, and revokes the account's active sessions.
- Admin-only `GET/POST /api/auth/users` lists or creates an invited account. `PATCH /api/auth/users/{user_id}` updates its `role` and `is_active`.
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

`POST /api/analyze` accepts JSON or `multipart/form-data`. JSON fields: `content` (required), `content_type` (default `text`), `title`, `guideline_ids`, `source_ids`, `alt_text`, and optional `allow_external_verification` (default `false`). Multipart accepts the same fields plus an optional PNG/JPEG/WEBP `file` image and JSON-encoded ID arrays.

```json
{
  "content": "Our product guarantees 100% success for every customer.",
  "content_type": "text",
  "title": "Product campaign",
  "guideline_ids": [],
  "source_ids": [],
  "allow_external_verification": false
}
```

Factual and promotional claim findings include `claim`, `verification_status` (`verified`, `contradicted`, or `unverified`), real `citations` when evidence was found, an explanation, confidence, and a suggested correction. No evidence is not treated as a contradiction. External lookup is opt-in and reports provider/configuration status in `external_verification`.

The `200` response has a persisted review `id`/`review_id`, `overall_status`, `total_issues`, grouped `summary`, `findings` (also available as `issues`), `analyzed_at`, and optional `image_analysis`. Findings include `category`, `severity`, `title`, `explanation`/`message`, `matched_text`, `suggestion`, `source`/`guideline`, confidence, and pending review status. No-issue analyses are still recorded for human workflow.

The deterministic rules identify configured prohibited terms, selected promotional-claim heuristics, simple factual-looking excerpts, and basic accessibility signals. Source retrieval reports candidate excerpts, source dates, expiry dates, and relevance. Without `EMBEDDING_MODEL`, retrieval uses local BM25 lexical ranking. With it, source text is chunked and vectors are cached in SQLite/SQLAlchemy storage; each analysis embeds the factual excerpt and ranks cached chunks by cosine similarity. The analysis response and health endpoint identify the retrieval mode. Candidate matches are never treated as proof or marked verified. Embedding provider errors return `502` instead of silently falling back to lexical ranking. If the LLM is explicitly configured, validated structured advisory findings are added to the local rules output; provider failures return `502`.

Example semantic retrieval configuration (without enabling LLM analysis):

```dotenv
LLM_API_BASE_URL=https://your-approved-provider.example/v1
LLM_API_KEY=your-provider-key
EMBEDDING_MODEL=your-embedding-model
```

Review the embedding provider's retention and training policies before enabling this mode. Query excerpts and selected source chunks are sent to the provider. Cached vectors persist in the same database as the source library; changing the model creates a separate cache.

Image analysis validates format, size, dimensions, and image integrity; reports dominant colours, aspect ratio/orientation, coarse edge density, transparency margins, and small source dimensions; and checks colours against an optional palette using approximate Euclidean RGB distance. With configured reference images, it also compares difference hashes to find possible asset variants. Palette and image-hash scores are rough heuristics, not perceptually reliable compliance checks. Layout metrics do not detect object boundaries or alignment, and reference similarity does not establish logo correctness, safe-zone compliance, or approval. If OCR is enabled and the host Tesseract binary is available, extracted text is checked against the text rules. Findings are review prompts only.

### Review workflow

- `GET /api/reviews?offset=0&limit=20&status=pending` → paginated `{items,total,offset,limit}`.
- `GET /api/reviews/{review_id}` → review with findings, comments, revisions.
- `GET /api/reviews/{review_id}/activity` → append-only application events for analysis, comments, revisions, and status changes.
- `PATCH /api/reviews/{review_id}/status` with `{"status":"in_review","reviewer":"Reviewer Name"}` → updated review; status audit event is persisted.
- `POST /api/reviews/{review_id}/comments` with `{"comment":"Please verify the source.","author":"Reviewer Name"}` → `201` comment.
- `POST /api/reviews/{review_id}/revisions` with `{"content":"Updated draft","title":"Revision 1"}` → `201` revision.

Supported statuses are `pending`, `in_review`, `approved`, and `changes_requested`. Status changes require an authenticated Admin or Reviewer; the recorded reviewer identity comes from the active session.

`WS /api/reviews/{review_id}/collaboration` provides process-local presence/typing events, ephemeral shared draft text, and broadcasts newly posted comments, status changes, and revisions. Send JSON `{"type":"typing","user":"Reviewer","active":true}`, `{"type":"presence","user":"Reviewer","active":true}`, or `{"type":"draft_changed","user":"Reviewer","content":"A shared draft"}`. Draft updates are transient until saved using the revision endpoint. Persisted comments continue to use the comments endpoint. Connections and presence are in memory and are not shared across multiple workers/instances. The activity log is append-only through this API, but is not cryptographically immutable.

### Analytics

- `GET /api/analytics/summary` aggregates stored reviews/findings by status, category, severity, and guideline.
- `GET /api/analytics/guideline-blind-spots` returns frequency indicators for triggered guidelines. `ambiguity_score` is normalized trigger frequency only; it is explicitly not proof of ambiguity.

## Deliberate MVP boundaries

This backend does not implement MFA, centralized SSO/OAuth, encryption-at-rest guarantees, private model hosting, a dedicated vector database, live external fact-checking, Figma/Slack/Docs/CMS integrations, CMS publishing, distributed worker pools, Temporal workflows, or cryptographically tamper-proof audit storage. Password recovery and account invitations are available only when SMTP is configured. SMTP credentials and reset/invitation links are not logged by the application; the configured mail provider necessarily receives the recipient address and message. Protect the bootstrap credentials and database, deploy behind HTTPS with `AUTH_COOKIE_SECURE=true`, configure edge rate limiting and backups, and complete a security review before production use. Login throttling is database-backed and shared across API processes using the configured database; it is additional protection, not a substitute for edge controls. Embedding retrieval is a lightweight application-database cache and is bounded by `MAX_RETRIEVAL_CHUNKS`; it is not a managed vector store. Visual checks are local heuristics, not a trained visual brand-governance model. WebSocket collaboration is lightweight and single-process.

### Existing database upgrade

No existing user or content table is altered by invitations. Startup `Base.metadata.create_all` adds only the `user_invitations` and `account_audit_events` tables to the configured database; existing accounts, sessions, and review data are preserved. Back up the database before upgrading and restart the API once to create those tables. No manual data migration is required. The existing bootstrap flow remains create-only and will not overwrite or recreate accounts in a non-empty database.

## Tests

```bash
pytest
```

Tests use an in-memory SQLite database and do not change the development database.
