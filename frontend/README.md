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

### Optional UI-only mock mode

Mock mode is off by default. Set `VITE_MOCK_API=true` to use the isolated `src/services/mockApi.js` for local interface development. Mock mode is visibly labeled throughout the workspace, and its illustrative findings are not represented as AI-generated results.

## API integration

Requests are centralized in `src/services/api.js` and use the documented endpoints:

- `GET /api/health`, `GET/POST/DELETE /api/guidelines`
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

Analysis supports selecting approved evidence sources and adding alternative text for an uploaded PNG, JPG, or WEBP. The frontend displays retrieved source excerpts as candidate evidence, not as verified facts. TXT, Markdown, and text-bearing PDF references can be uploaded from the Evidence Sources page.

## Known limitations

- No authentication or authorization is implemented. Review actions are workflow controls, not security permissions.
- Guideline edit is unavailable because the agreed API contract has no update endpoint.
- OCR requires the backend `OCR_ENABLED=true` setting and an installed Tesseract executable.
- Real-time presence and updates use WebSockets and are limited to a single backend process.
- Shared draft edits are ephemeral until an explicit revision save.
- Brand palette comparison requires configured backend hex colours and uses an approximate RGB heuristic.
- Optional LLM analysis requires explicit backend provider configuration; submitted content and guideline context are sent to that configured service.
- PDF upload is supported for approved evidence sources only; direct PDF content review, DOCX, Figma, and other design integrations are not implemented.
- PDF, DOCX, Figma, and other document/design integrations are not implemented.
- The application does not invent live statistics: unavailable API values are shown as empty states or em dashes.

## Production build

```bash
npm run build
npm run preview
```
