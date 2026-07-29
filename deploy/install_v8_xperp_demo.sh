#!/usr/bin/env bash
# Install the isolated V8 unit inactive. This script never starts or enables it.
set -euo pipefail

APP_DIR="${1:-/srv/matibot}"
ENV_FILE="${2:-/etc/matibot/v8-xperp-demo.env}"
RUN_USER="${3:-${SUDO_USER:-matibot}}"
UNIT_NAME="matibot-v8-xperp-demo.service"
TELEGRAM_UNIT="matibot-v8-xperp-telegram.service"

if systemctl is-active --quiet "$UNIT_NAME" || systemctl is-active --quiet "$TELEGRAM_UNIT"; then
    echo "Refusing to replace an active V8 or V8 Telegram unit; stop both first" >&2
    exit 2
fi
APP_DIR="$(readlink -f "$APP_DIR")"
ENV_FILE="$(readlink -f "$ENV_FILE")"
if [[ "$APP_DIR" != /srv/* ]] || [[ "$ENV_FILE" != /etc/matibot/* ]]; then
    echo "APP_DIR must be under /srv and ENV_FILE under /etc/matibot" >&2
    exit 2
fi
if [[ ! "$RUN_USER" =~ ^[a-z_][a-z0-9_-]*[$]?$ ]]; then
    echo "RUN_USER is not a safe local account name" >&2
    exit 2
fi
if ! id "$RUN_USER" >/dev/null 2>&1; then
    echo "RUN_USER does not exist" >&2
    exit 2
fi
if [[ ! -x "$APP_DIR/.venv/bin/python" ]] || [[ ! -f "$ENV_FILE" ]]; then
    echo "Python virtualenv or environment file is missing" >&2
    exit 2
fi

RUN_GROUP="$(id -gn "$RUN_USER")"
PYTHON="$APP_DIR/.venv/bin/python"
DATA_RUNTIME_DIR="$APP_DIR/data/runtime"
RUNTIME_DIR="$DATA_RUNTIME_DIR/v8_xperp_demo"
install -d -m 0700 -o "$RUN_USER" -g "$RUN_GROUP" "$DATA_RUNTIME_DIR" "$RUNTIME_DIR"
chown root:root "$ENV_FILE"
chmod 0600 "$ENV_FILE"

for unit in "$UNIT_NAME" "$TELEGRAM_UNIT"; do
    sed \
        -e "s|__APP_DIR__|$APP_DIR|g" \
        -e "s|__ENV_FILE__|$ENV_FILE|g" \
        -e "s|__PYTHON__|$PYTHON|g" \
        -e "s|__RUN_USER__|$RUN_USER|g" \
        -e "s|__RUN_GROUP__|$RUN_GROUP|g" \
        -e "s|__DATA_RUNTIME_DIR__|$DATA_RUNTIME_DIR|g" \
        -e "s|__RUNTIME_DIR__|$RUNTIME_DIR|g" \
        "$APP_DIR/deploy/$unit" \
        > "/etc/systemd/system/$unit"
    chmod 0644 "/etc/systemd/system/$unit"
done
systemctl daemon-reload
systemctl disable "$UNIT_NAME" >/dev/null 2>&1 || true
systemctl disable "$TELEGRAM_UNIT" >/dev/null 2>&1 || true

echo "Installed inactive: $UNIT_NAME and $TELEGRAM_UNIT"
echo "Run the documented preactivation command before enabling this unit."
