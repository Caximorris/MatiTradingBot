#!/usr/bin/env python
"""Registra el bot Swing v5 con ejecucion sobre la cuenta DEMO real de OKX.

Mismo patron que swing_paper_setup.py. El bot corre la estrategia v5 SIN cambios (mismos
datos de mercado reales que v5/v6/legacy); solo cambia el backend de ejecucion: las ordenes
van a OKX demo trading (x-simulated-trading:1) via core/okx_demo_client.py.

Requisitos previos (manuales, del usuario):
  1. Entrar en OKX -> modo Demo trading -> crear una API key DEMO (las keys de la cuenta
     real NO funcionan con el header de simulacion).
  2. Añadir a .env: OKX_DEMO_API_KEY, OKX_DEMO_SECRET_KEY, OKX_DEMO_PASSPHRASE.
  3. Fondos demo: OKX los da al activar demo trading. Idealmente la cuenta demo deberia
     tener solo USDT; si ya tiene BTC, el bot NO hace la compra INIT (ve base>0 y pasa
     directo a rebalancear en la siguiente evaluacion 4H).

Uso (en la VM):
  python tools/okx_demo_setup.py            # registra pausado (is_active=False)
  python tools/okx_demo_setup.py --enable   # registra y activa
  sudo systemctl restart matibot            # el scheduler descubre bots al arrancar
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

INSTANCE_ID = "demo"
PORTFOLIO_ID = "okx_demo"


def demo_config() -> dict:
    # v5 exacto (defaults de SwingAllocatorConfig) + enrutado de ejecucion. Igual que el
    # bot v5 paper: sin overrides de estrategia, solo identidad y backend.
    return {
        "instance_id": INSTANCE_ID,
        "paper_portfolio_id": PORTFOLIO_ID,   # nombre del espejo paper_state_okx_demo.json
        "execution": "okx_demo",              # cli/live_cmds.py -> OKXDemoClient
        # Cuenta EEA/MiCA (2026-07-13): USDT bloqueado por compliance (sCode 51155).
        # Señales en BTC-USDT (feed real, paridad backtest); ordenes en BTC-USDC.
        "execution_quote": "USDC",
        "persist_live_rebalance_log": True,
    }


def bot_name(symbol: str) -> str:
    sym = symbol.upper().replace("-", "_").lower()
    return f"swing_allocator_{INSTANCE_ID}_{sym}"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="BTC-USDT")
    p.add_argument("--enable", action="store_true")
    args = p.parse_args()

    from core.database import get_or_create_bot_state, get_session, init_db

    init_db()
    cfg = demo_config()
    name = bot_name(args.symbol)
    with get_session() as s:
        state = get_or_create_bot_state(s, name, args.symbol.upper(), config=cfg)
        state.set_config(cfg)
        state.is_active = bool(args.enable)

    print(f"registered,{name},{args.symbol.upper()},active={args.enable}")
    print(json.dumps(cfg, sort_keys=True))
    print("NOTA: requiere OKX_DEMO_API_KEY/SECRET/PASSPHRASE en .env (key creada en modo "
          "demo trading) y 'systemctl restart matibot' para que el scheduler lo levante.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
