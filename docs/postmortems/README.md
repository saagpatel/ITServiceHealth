# Postmortems

Auto-generated Markdown drafts written here when a Pulse-monitored service recovers from a non-operational state. Each file is a Google-SRE-style postmortem template with auto-filled facts (summary, timeline, impact) and `_TODO_` placeholders for the judgment sections a human needs to author.

## Filename Pattern

`{service_id}-{started_at_compact}-{6_char_sha}.md`

One postmortem per incident; the same incident is never double-written.

## Auto-filled Sections

- **Summary** — incident duration, affected service, status.
- **Impact** — peak severity, duration, event count, affected downstream services.
- **Timeline** — each status transition with timestamp and transition reason.

## Human-authored Sections

- **Root Cause** — why the service failed (vendor issue, configuration, dependency, etc.).
- **What Went Well / What Went Poorly / What Got Lucky** — assessment of detection, response, and luck.
- **Action Items** — organized by Prevent, Mitigate, Detect, Repair.

## Review Workflow

1. Read the generated draft; fill in the human-authored sections marked `_TODO_`.
2. Flip `status: draft` → `status: reviewed` in the YAML frontmatter.
3. `git add` + commit when ready.
4. (Optional) Cross-reference in your team wiki or postmortem library.

## Gating

Generation is gated behind `POSTMORTEMS_ENABLED=true` in backend env. Off by default. See `backend/app/config.py`.
