# Executive-view screenshots

- `exec-operational.png` — live operational state, all services healthy
- `exec-major.png` — mocked `major_outage` banner + 3 realistic impact rows (chat platform / identity provider / video conferencing)

Both captured at 3840×4232 (1920-wide viewport × 2 DPR × full-page scroll).

## Regenerating

`frontend/scripts/capture-screenshots.mjs` uses `puppeteer-core` + your system Chrome to capture both states and write them here. `puppeteer-core` is not a project dependency — install it ad-hoc for the capture, don't commit it.

```bash
# one-time, while the dev stack is up on :5173 + :8000
cd frontend
npm install --no-save --legacy-peer-deps puppeteer-core
node scripts/capture-screenshots.mjs
```

Output lands in `docs/executive-view-redesign/screenshots/`.

### Major-outage state

The script DOM-mocks the major-outage panel, tiles, and the first three impact rows — the live backend can't produce `major_outage` without an admin write. If you want a fully live major-outage screenshot, start the backend with `ADMIN_API_TOKEN=<secret>` set and `POST /api/admin/status` before running the script; then remove the `captureMajor` DOM-eval block.
