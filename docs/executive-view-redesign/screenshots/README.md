# Executive-view screenshots

- `exec-operational.png` — target: live operational state, all services healthy
- `exec-major.png` — target: mocked `major_outage` banner + 3 realistic impact rows (chat platform / identity provider / video conferencing)

The PNG files are absent from this checkout. The capture script uses a 1920×1080 viewport at 2 DPR and full-page capture; output height depends on page content.

## Regenerating

`frontend/scripts/capture-screenshots.mjs` uses `puppeteer-core` + your system Chrome to capture both states and write them to `frontend/docs/executive-view-redesign/screenshots/`. `puppeteer-core` is not a project dependency — install it ad-hoc for the capture, don't commit it.

```bash
# one-time, while the dev stack is up on :5173 + :8000
cd frontend
npm install --no-save --legacy-peer-deps puppeteer-core
node scripts/capture-screenshots.mjs --allow-local-browser
```

Output lands in `frontend/docs/executive-view-redesign/screenshots/`; create that directory first, since the script does not create it.

### Major-outage state

The script DOM-mocks the major-outage panel, tiles, and the first three impact rows — the live backend can't produce `major_outage` without an admin write. If you want a fully live major-outage screenshot, start the backend with `ADMIN_API_TOKEN=<secret>` set and `POST /api/admin/status` before running the script; then remove the `captureMajor` DOM-eval block.
