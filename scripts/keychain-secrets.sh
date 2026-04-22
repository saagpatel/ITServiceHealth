#!/usr/bin/env bash
# keychain-secrets.sh — provision + export Mac Mini secrets via macOS Keychain.
#
# Why Keychain?
#   - Launch plists are world-readable under /Library/LaunchDaemons; any
#     `launchctl list -x` shows the EnvironmentVariables. Hardcoding
#     SLACK_WEBHOOK_URL there leaks it to every local user.
#   - Keychain entries are owned by root (when stored under the System
#     keychain) and require explicit retrieval via `security(1)`.
#
# Two commands:
#   provision      : prompt for each secret interactively + store it
#   export         : emit `export FOO=value` lines for `source`ing by
#                    the launchd wrapper shell script or a dev shell
#
# The main app reads these via standard env vars (SLACK_WEBHOOK_URL,
# ADMIN_API_TOKEN, etc.) so this script is the only piece that knows
# about Keychain.

set -euo pipefail

SERVICE_NAME="it-health-dashboard"

# Secrets the dashboard looks for. Add here when we introduce new ones.
SECRETS=(
    SLACK_WEBHOOK_URL
    POLLER_HEALTH_SLACK_WEBHOOK_URL
    ADMIN_API_TOKEN
    SENTRY_DSN
    HEALTHCHECK_PING_URL
)

usage() {
    cat <<EOF
Usage: $0 <command>

Commands:
  provision   Prompt for each secret and store in macOS Keychain.
              Idempotent — updates existing entries in place.
  export      Print 'export FOO=bar' lines for known secrets to stdout.
              Intended to be 'source'd by the launchd wrapper script.
  get NAME    Print a single secret's value (for ad-hoc lookup).
  list        List which secret slots have values and which don't.

Storage: System Keychain, service=$SERVICE_NAME, account=<env-var-name>.
EOF
    exit 1
}

require_sudo() {
    if [[ $EUID -ne 0 ]]; then
        echo "This command writes to the System keychain — re-run with sudo." >&2
        exit 1
    fi
}

cmd_provision() {
    require_sudo
    for name in "${SECRETS[@]}"; do
        read -rp "$name (leave empty to skip): " -s value
        echo
        if [[ -z "$value" ]]; then
            echo "  skipped $name"
            continue
        fi
        # -U updates existing, -s/-a sets service + account, -w provides
        # the secret via arg rather than prompting (we already did).
        # -T "" means no apps are pre-trusted — every access goes
        # through an explicit security(1) call, no GUI prompts.
        security add-generic-password \
            -s "$SERVICE_NAME" -a "$name" -w "$value" -U -T "" /Library/Keychains/System.keychain
        echo "  stored $name"
    done
}

cmd_export() {
    for name in "${SECRETS[@]}"; do
        value=$(security find-generic-password \
            -s "$SERVICE_NAME" -a "$name" -w 2>/dev/null || true)
        if [[ -n "$value" ]]; then
            # %q escapes for safe shell reuse
            printf 'export %s=%q\n' "$name" "$value"
        fi
    done
}

cmd_get() {
    local name=${1:-}
    [[ -z "$name" ]] && { echo "get: missing secret name" >&2; exit 1; }
    security find-generic-password -s "$SERVICE_NAME" -a "$name" -w
}

cmd_list() {
    for name in "${SECRETS[@]}"; do
        if security find-generic-password \
            -s "$SERVICE_NAME" -a "$name" >/dev/null 2>&1; then
            echo "  [✓] $name"
        else
            echo "  [ ] $name"
        fi
    done
}

case "${1:-}" in
    provision) cmd_provision ;;
    export)    cmd_export ;;
    get)       shift; cmd_get "$@" ;;
    list)      cmd_list ;;
    *)         usage ;;
esac
