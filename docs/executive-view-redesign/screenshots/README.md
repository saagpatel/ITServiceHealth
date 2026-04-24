# Executive-view screenshots

Target artifacts (per Phase 3 acceptance): `exec-operational.png` and `exec-major.png`, ≥1920 px wide, for the pitch deck (Session 3) and case study (Session 4).

Phase 3 verified visually that both states render correctly in the browser at 1920×1080. Final PNG capture is a manual step — the headless preview harness used during development can render the states but doesn't expose a filesystem-writing screenshot API.

## Capture procedure

Run the dashboard locally (backend on `:8000`, `npm run dev` on `:5173`), then:

### `exec-operational.png` — live state

1. Ensure the backend is healthy (`curl http://127.0.0.1:8000/api/summary` reports `overall_status: operational`).
2. Resize Chrome to exactly 1920×1080 (DevTools → Device Toolbar → Responsive → 1920×1080).
3. Open Executive view.
4. DevTools → Cmd-Shift-P → "Capture full size screenshot".
5. Save as `exec-operational.png` in this directory.

### `exec-major.png` — major outage state

Requires a service in `major_outage`. Two options:

**Option A — admin endpoint** (preferred; start the backend with `ADMIN_API_TOKEN=<secret>`):

```bash
curl -X POST http://127.0.0.1:8000/api/admin/status \
  -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"service_id":"slack","new_status":"major_outage","reason":"pitch-deck screenshot"}'
```

Then repeat the capture procedure above. Revert with `"new_status":"operational"` when done.

**Option B — seed-data override**: patch `scripts/seed_demo_data.py` to include at least one service with `major_outage` status, run with `SEED_DEMO_DATA=true`, then capture.

## Why not automated

The development harness captures screenshots inline for verification but doesn't write to disk. Adding a puppeteer/playwright dependency just for this artifact step isn't justified — a once-per-release manual capture is cheaper.
