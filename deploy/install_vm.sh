#!/usr/bin/env bash
# Instalador para VM Linux (Ubuntu 22.04/24.04 — Oracle Free / GCP e2-micro).
# Ejecutar DESDE la raiz del repo ya clonado:
#   git clone https://github.com/Caximorris/MatiTradingBot.git && cd MatiTradingBot
#   bash deploy/install_vm.sh
# Idempotente: se puede re-ejecutar sin romper nada.
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_USER="$(whoami)"
cd "$APP_DIR"

echo "== 1/6 Dependencias del sistema =="
sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv python3-pip git

echo "== 2/6 Swap 1G (necesario en e2-micro con 1GB RAM; inofensivo en maquinas grandes) =="
if [ ! -f /swapfile ]; then
    sudo fallocate -l 1G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab > /dev/null
fi

echo "== 3/6 Entorno Python =="
if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

echo "== 4/6 Configuracion .env =="
if [ ! -f .env ]; then
    cp .env.example .env
    # Paper con datos de mercado REALES (el sandbox demo rompe la paridad con backtest)
    sed -i 's/^OKX_SANDBOX=true/OKX_SANDBOX=false/' .env
    echo ""
    echo ">>> EDITA .env AHORA y rellena TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID <<<"
    echo ">>> (nano .env) — luego re-ejecuta este script para continuar        <<<"
    exit 0
fi

echo "== 5/6 Registrar y activar el bot Swing en paper =="
.venv/bin/python main.py bot enable swing_allocator_btc_usdt BTC-USDT

echo "== 6/6 Servicios systemd + cron diario =="
for unit in matibot matibot-telegram; do
    sed -e "s|__APP_DIR__|$APP_DIR|g" -e "s|__RUN_USER__|$RUN_USER|g" \
        "deploy/${unit}.service" | sudo tee "/etc/systemd/system/${unit}.service" > /dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --now matibot matibot-telegram
chmod +x deploy/daily_checks.sh

# Cron: paridad + degradacion cada dia a las 12:10 UTC (el parity check de las 12:00 del plan)
CRON_LINE="10 12 * * * $APP_DIR/deploy/daily_checks.sh"
( crontab -l 2>/dev/null | grep -vF "daily_checks.sh" ; echo "$CRON_LINE" ) | crontab -

echo ""
echo "LISTO. Comprobaciones:"
echo "  systemctl status matibot matibot-telegram"
echo "  journalctl -u matibot -f          # logs del bot en vivo"
echo "  .venv/bin/python main.py status   # estado desde CLI"
echo "En Telegram deberias haber recibido: 'Control remoto conectado'."
