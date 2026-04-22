#!/usr/bin/env bash
# run-with-keychain.sh — launchd wrapper that pulls secrets from Keychain
# and exec's the dashboard. Point the plist's ProgramArguments at this
# script instead of at python+uvicorn directly.
#
# The plist stays free of secret material; this script does the Keychain
# reads at process start and exports them into the child's env.

set -euo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
APP_ROOT=$(dirname "$HERE")

# Fold every known secret from Keychain into our env. Missing secrets
# are silently skipped — the app treats unset SENTRY_DSN etc. as opt-out.
eval "$("$HERE/keychain-secrets.sh" export)"

# hand off to uvicorn; exec replaces the shell so signals propagate
exec "$APP_ROOT/.venv/bin/python3" -m uvicorn \
    app.main:app \
    --host "${HOST:-0.0.0.0}" \
    --port "${PORT:-8000}" \
    --workers "${WORKERS:-2}" \
    --log-level "${UVICORN_LOG_LEVEL:-warning}" \
    --timeout-graceful-shutdown 30
