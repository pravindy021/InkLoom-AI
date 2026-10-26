# InkLoom AI frontend

Responsive React/Vite workspace for brand-guideline content review, human approvals, and analytics.

## Requirements

- Node.js 18+
- The InkLoom FastAPI service, unless local mock mode is explicitly enabled

## Run locally

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

Set `VITE_API_BASE_URL` in `.env` to the FastAPI origin (default: `http://localhost:8000`). The backend must allow browser requests from the Vite origin through CORS.

For real API mode, configure the backend's `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD` before starting the API. The first account on an empty database is the Admin. Sign in and open **Admin dashboard → Invite user** to invite additional members. Set backend SMTP configuration and `PASSWORD_RESET_BASE_URL=http://localhost:5173`; invitation creation is unavailable until SMTP is configured. Authenticated requests use an HttpOnly cookie, so use the same hostname (`localhost`, not a mix of `localhost` and `127.0.0.1`) for the frontend and API during local development.

### Optional UI-only mock mode

Mock mode is off by default. Set `VITE_MOCK_API=true` to use the isolated `src/services/mockApi.js` for local interface development. Mock mode is visibly labeled throughout the workspace, and its illustrative findings are not represented as AI-generated results.

## API integration

Requests are centralized in `src/services/api.js` and use the documented endpoints:

- `GET /api/health`, `GET/POST/DELETE /api/guidelines`
- `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`, `POST /api/auth/password`
- `POST /api/auth/password/forgot`, `POST /api/auth/password/reset`
- Public `POST /api/auth/invitations/accept` (single-use invitation token from the email fragment)
- Admin-only `GET/POST/PATCH /api/auth/users`, `POST /api/auth/users/{user_id}/invitation`
- `POST /api/analyze`
- `GET /api/reviews`, `GET /api/reviews/{review_id}`
- `PATCH /api/reviews/{review_id}/status`
- `POST /api/reviews/{review_id}/comments`
- `POST /api/reviews/{review_id}/revisions`
- `GET/POST/DELETE /api/sources`
- `GET /api/reviews/{review_id}/activity`
- `WS /api/reviews/{review_id}/collaboration`
- `GET /api/analytics/summary`
- `GET /api/analytics/guideline-blind-spots`

Analysis supports selecting approved evidence sources and adding alternative text for an uploaded PNG, JPG, or WEBP. Factual and promotional claims show a verification status, explanation, confidence, suggested correction, and real citations when available. Results are advisory; lack of evidence is not proof a claim is false, and human approval remains required. Optional Brave Search is disabled unless configured on the backend and explicitly selected per analysis. When selected, only extracted claim excerpts are sent to Brave Search; the full draft and image are not sent by that factual lookup. Results are restricted to configured trusted domains. TXT, Markdown, and text-bearing PDF references can be uploaded from the Evidence Sources page.

## Known limitations

- Authentication uses the backend's invite-only local account flow and role checks. The bootstrap Admin is provisioned from environment configuration only on an empty user database. Admin-created invitations expire after 48 hours and can be used once; members set their own password before activation. Public self-registration is disabled. Explicitly configured mock mode disables authentication and must not be treated as a secured environment.
- Guideline edit is unavailable because the agreed API contract has no update endpoint.
- OCR requires the backend `OCR_ENABLED=true` setting and an installed Tesseract executable.
- Real-time presence and updates use WebSockets and are limited to a single backend process.
- Shared draft edits are ephemeral until an explicit revision save.
- Brand palette comparison requires configured backend hex colours and uses an approximate RGB heuristic.
- Optional LLM analysis requires explicit backend provider configuration; submitted content and guideline context are sent to that configured service.
- PDF upload is supported for approved evidence sources only; direct PDF content review, DOCX, Figma, and other design integrations are not implemented.
- PDF, DOCX, Figma, and other document/design integrations are not implemented.
- Email recovery is available only when the backend reports SMTP configured. The backend sends a single-use link that expires after 20 minutes, stores only its token hash, and revokes existing sessions after reset. Recovery requests are rate-limited and have generic responses to avoid account enumeration. Configure SMTP and `PASSWORD_RESET_BASE_URL` on the backend; the mail provider receives the recipient address and recovery message.
- User invitations use the same configured SMTP transport and send only an expiring link; invitation tokens are stored as digests and are never returned by the API. Resending invalidates earlier pending links. An email provider receives the recipient address and invitation message.
- The application does not invent live statistics: unavailable API values are shown as empty states or em dashes.

## Production build

```bash
npm run build
npm run preview
```
