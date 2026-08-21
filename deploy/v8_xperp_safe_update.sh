#!/usr/bin/env bash
# Pull V8 code and reload only its read-only Telegram companion.
# It never starts, restarts, enables, resumes, or flattens the V8 Demo executor.
set -euo pipefail

APP_DIR="${1:-/srv/matibot}"
CONFIRM="${2:-}"
DEPENDENCIES_SYNCED="${3:-}"
TELEGRAM_UNIT="matibot-v8-xperp-telegram.service"
DEMO_UNIT="matibot-v8-xperp-demo.service"

if [[ "$CONFIRM" != "--confirm-v8-telegram-reload" ]]; then
    echo "Refusing update: pass --confirm-v8-telegram-reload." >&2
    exit 2
fi

cd "$APP_DIR"
if [[ -n "$(git status --porcelain)" ]]; then
    echo "Refusing update: repository worktree is dirty." >&2
    exit 2
fi

before="$(git rev-parse HEAD)"
git pull --ff-only
after="$(git rev-parse HEAD)"
if [[ "$before" == "$after" ]]; then
    if [[ "$DEPENDENCIES_SYNCED" == "--dependencies-synced" ]]; then
        sudo systemctl restart "$TELEGRAM_UNIT"
        echo "Reloaded $TELEGRAM_UNIT after the explicit dependency synchronization."
        echo "$DEMO_UNIT was not started, restarted, enabled, resumed, or modified."
        exit 0
    fi
    echo "No V8 update: repository is already current."
    exit 0
fi

changed="$(git diff --name-only "$before" "$after")"
if grep -Eq '^(requirements|pyproject\.toml|uv\.lock|poetry\.lock)' <<<"$changed"; then
    if [[ "$DEPENDENCIES_SYNCED" != "--dependencies-synced" ]]; then
        echo "Dependencies changed; rebuild the virtual environment explicitly, then rerun with --dependencies-synced." >&2
        exit 3
    fi
fi

if grep -Eq '^(tools/v8_xperp_telegram\.py|execution/v8_xperp/|tools/v8_xperp_demo\.py)' <<<"$changed"; then
    sudo systemctl restart "$TELEGRAM_UNIT"
    echo "Reloaded $TELEGRAM_UNIT at $after."
else
    echo "No V8 runtime code changed; Telegram companion was not reloaded."
fi

echo "$DEMO_UNIT was not started, restarted, enabled, resumed, or modified."
