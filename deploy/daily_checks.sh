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

# Pipeline forward de funding (v6): mantiene el snapshot OKX versionado por fuente.
# Sin un snapshot fresco el overlay habilitado falla cerrado; el umbral 26h deja margen
# sobre la cadencia diaria sin sustituir la configuracion por v5.
funding_out=$("$PY" "$APP_DIR/tools/funding_refresh.py" --source okx --stale-hours 26 2>&1)
funding_rc=$?
echo "$funding_out" >> "$LOG"
if [ $funding_rc -ne 0 ]; then
    "$PY" "$APP_DIR/tools/tg_send.py" "ALERTA FUNDING (v6): snapshot OKX sin actualizar. El overlay Swing habilitado falla cerrado; no degrada a v5. Detalle: ${funding_out}"
fi

parity_out=$("$PY" "$APP_DIR/tools/swing_parity_check.py" 2>&1)
parity_rc=$?
echo "$parity_out" >> "$LOG"

degr_out=$("$PY" "$APP_DIR/tools/degradation_report.py" 2>&1)
echo "$degr_out" >> "$LOG"

prop_out=$("$PY" "$APP_DIR/tools/prop_cft_status.py" 2>&1)
echo "$prop_out" >> "$LOG"

if [ $parity_rc -ne 0 ]; then
    "$PY" "$APP_DIR/tools/tg_send.py" "ALERTA PARIDAD (F15): live y backtest DIVERGEN. Esto es un bug por definicion: pausa el bot (/pause) e investiga. Detalle: ${parity_out}"
else
    target=$(echo "$parity_out" | grep '^live_target' | cut -d, -f2)
    "$PY" "$APP_DIR/tools/tg_send.py" "Check diario OK. Paridad F15: OK (target ${target}). Degradacion F19: $(echo "$degr_out" | tail -3). Prop/CFT: $(echo "$prop_out" | head -4)"
fi
