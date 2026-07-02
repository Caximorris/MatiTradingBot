#!/usr/bin/env bash
# Chequeos diarios del paper trading (cron, ver install_vm.sh):
#   1. Paridad live vs backtest (F15) — divergencia = ALERTA (es el criterio go/no-go de 30 dias)
#   2. Reporte de degradacion (F19)
# Resultado resumido por Telegram y log completo en data/runtime/daily_checks.log
set -u
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="$APP_DIR/.venv/bin/python"
LOG="$APP_DIR/data/runtime/daily_checks.log"
mkdir -p "$APP_DIR/data/runtime"

echo "===== daily_checks $(date -u +%Y-%m-%dT%H:%M:%SZ) =====" >> "$LOG"

parity_out=$("$PY" "$APP_DIR/tools/swing_parity_check.py" 2>&1)
parity_rc=$?
echo "$parity_out" >> "$LOG"

degr_out=$("$PY" "$APP_DIR/tools/degradation_report.py" 2>&1)
echo "$degr_out" >> "$LOG"

if [ $parity_rc -ne 0 ]; then
    "$PY" "$APP_DIR/tools/tg_send.py" "ALERTA PARIDAD (F15): live y backtest DIVERGEN. Esto es un bug por definicion: pausa el bot (/pause) e investiga. Detalle: ${parity_out}"
else
    target=$(echo "$parity_out" | grep '^live_target' | cut -d, -f2)
    "$PY" "$APP_DIR/tools/tg_send.py" "Check diario OK. Paridad F15: OK (target ${target}). Degradacion F19: $(echo "$degr_out" | tail -3)"
fi
