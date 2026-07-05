#!/usr/bin/env bash
# Registra PropSwing CFT paper en la VM existente.
# Uso:
#   bash deploy/setup_prop_cft_paper.sh              # registra pausado
#   ENABLE_PROP_CFT=true bash deploy/setup_prop_cft_paper.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"

ENABLE_FLAG=""
if [ "${ENABLE_PROP_CFT:-false}" = "true" ]; then
    ENABLE_FLAG="--enable"
fi

.venv/bin/python tools/prop_cft_setup.py \
    --account-size "${CFT_ACCOUNT_SIZE:-50000}" \
    --phase "${CFT_PHASE:-p1}" \
    --daily-dd "${CFT_DAILY_DD:-0.06}" \
    --max-loss "${CFT_MAX_LOSS:-0.12}" \
    $ENABLE_FLAG

echo ""
echo "Prop/CFT registrado. Comandos utiles:"
echo "  .venv/bin/python main.py bot list"
echo "  .venv/bin/python tools/prop_cft_status.py"
echo "  sudo systemctl restart matibot"
echo "  Telegram: /prop /prop_report /prop_pause /prop_resume"
