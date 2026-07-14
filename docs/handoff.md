# Handoff 2026-07-13 — MatiTradingBot

Este archivo es el punto de arranque para continuar mañana desde otro PC.

> **ESTADO ACTUAL:** trabajar sobre `main`. Swing v6-2 es el default congelado; v5 queda como
> control/rollback. El cliente OKX Demo esta desplegado; el repo lo configura con v6-2, pendiente
> confirmar `git pull` + restart en la VM. El estado operativo y los siguientes pasos viven en
> `SESSION.md`. Commit de sincronizacion inicial:
> `0d24671`; este handoff se mantiene actualizado para continuar desde otro PC.

## 1. Estado rapido

- Rama de trabajo: `main`.
- Default de estrategia: **Swing Allocator v6-2**, congelado.
- Paper Swing v6/v5/legacy: desplegado en VM GCP `matitrbot`, con Telegram y checks diarios.
- Prop/CFT: paper operativo preparado, no comprado challenge, no live.
- Swing v5: control paper y rollback exacto (`use_phase_policy_router=false`,
  `use_funding_overlay=false`).
- Tests al cierre: `233 passed`.

## 2. Archivos que debes leer primero

1. `AGENTS.md`
2. `SESSION.md`
3. Este archivo
4. `docs/ops/deploy-paper.md`
5. `docs/swing/v6-plan.md`

Para Prop/CFT:

6. `docs/prop/hyrotrader-plan.md`

Para historial de versiones:

7. `backtests/STRATEGY_VERSIONS.md`

## 3. Que esta congelado

### Swing v6-2

No optimizar de nuevo por ahora. La fase actual es forward/paper:

- F13: smoke 24h de VM.
- F15: 30 dias de paridad live/backtest.
- F19: degradacion/frecuencia de rebalanceos.

Anclas v6-2:

| Window | Costes | Final | CAGR | Max DD | Rebalances | BTC vs B&H |
|---|---:|---:|---:|---:|---:|---:|
| 2015-2026 | realistic | $9.505M | +86.51% | -52.73% | 70 | 0.8499 |
| 2018-2026 | realistic | $229.0k | +47.90% | -53.72% | 53 | 0.8785 |
| 2015-2026 | conservative | $9.255M | +86.06% | -52.88% | 70 | 0.8281 |

No reabrir sin datos nuevos:

- `min_btc_pct=0.0` como default.
- Caps globales de `max_btc_pct`.
- Latch del bull peak cap.
- Cap sobre bear_onset.
- Cooldown/ADX para arreglar solo Q4 2025.

### Prop/CFT

Candidato vivo solo para **CFT 2-Phase**:

```json
{
  "entry_mode": "breakout",
  "risk_per_trade": 0.018,
  "tp1_r": 1.5,
  "allow_shorts": true,
  "max_notional_pct": 0.8,
  "model_funding": true,
  "entry_halving_phases": "bear_onset,accumulation"
}
```

Resultados backtest CFT bybit_cons:

| Window | Pass | Breach | Timeout |
|---|---:|---:|---:|
| 2020-2026 default | 74.8% | 2.0% | 23.2% |
| 2018-2026 default | 72.2% | 5.1% | 22.7% |
| 2018 shift -60 | 71.9% | 13.9% | 14.2% |

No comprar challenge sin:

- paper CFT reciente;
- confirmacion operativa de CFT/Bybit desde España;
- reglas reales de cuenta y API verificadas por escrito.

## 4. Cambios preparados en esta rama

### Prop/CFT operativo

- `core/cft_monitor.py`: monitor CFT con estado en `data/runtime/prop_cft_status.json`.
- `strategies/prop_swing.py`: persistencia live/paper de posicion/dia/funding idx en BotState
  `prop_swing`; journal operativo `data/runtime/prop_live_journal.jsonl`; hard-stop CFT.
- `tools/prop_cft_setup.py`: registra bot PropSwing CFT paper.
- `tools/paper_fleet_setup.py`: deja activo exactamente v6 simulado + v6 OKX Demo + Prop Firm,
  elimina registros legacy/v5 y desactiva los demas bots sin borrar historicos ni wallets.
- `tools/prop_cft_status.py`: imprime estado del monitor.
- `tools/prop_telegram.py`: formateo Telegram de Prop/CFT.
- `deploy/setup_prop_cft_paper.sh`: setup idempotente en VM.
- `deploy/daily_checks.sh`: incluye estado Prop/CFT en check diario.
- `tools/telegram_remote.py`: comandos `/prop`, `/prop_report`, `/prop_pause`, `/prop_resume`.
- `tools/tg_menu.py`: panel persistente de botones, con atajos sin argumentos para v6/demo/Prop.
- `tools/status_snapshot.py`: vista pura multi-cartera para `main.py status`; separa señal,
  ejecucion y quote visible, filtra filas internas y convierte ticks a Europe/Madrid.

### Swing v6 default: simulado + OKX Demo

- `docs/swing/v6-plan.md`: decision, validacion y rollback de v6.
- `strategies/swing_phase_policy.py`: router `v5_equiv` con paridad exacta.
- `strategies/swing_funding_overlay.py`: overlay de funding cerrado/deduplicado.
- `tools/swing_paper_setup.py`: registra Swing v6 paper aislado (`paper_portfolio_id=swing_v6`).
- Enfoque actual: paper OOS del default V6-2 (`accumulation`, p10/p90, `+0.05`, ttl 7d)
  en cartera simulada y cuenta OKX Demo. El registro v5 se retira, preservando su rollback.

### Prop research

Nuevos tools de investigacion ya usados:

- `tools/bybit_public_cost_probe.py`
- `tools/prop_breach_audit.py`
- `tools/prop_phase_frontier.py`
- `tools/prop_phase_matrix.py`
- `tools/prop_risk_frontier.py`
- `tools/prop_router_vs_swing.py`

## 5. Como arrancar en otro PC

```bash
git clone https://github.com/Caximorris/MatiTradingBot.git
cd MatiTradingBot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python main.py mode
python main.py bot list
```

Si estas en Windows PowerShell:

```powershell
git clone https://github.com/Caximorris/MatiTradingBot.git
cd MatiTradingBot
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

No copies `.env` ni `trading.db` desde Git: no se versionan.

## 6. VM GCP

Runbook: `docs/ops/deploy-paper.md`.

Comandos Telegram Swing (`bot` = v6/demo; las acciones habituales tambien estan en el panel):

- `/status [bot]` — resumen de todos, o detalle de uno
- `/bots` — bots swing registrados y su cartera
- `/report [bot] [n]`
- `/signals` — target/senales live (v6 canonico, un solo calculo)
- `/parity`
- `/equity [bot] [dias]`
- `/chart [bot] [dias]`
- `/health`
- `/logs`
- `/backup` — abarca todas las `paper_state_*.json`
- `/restart`
- `/update`
- `/pause`
- `/resume`

Comandos Telegram Prop/CFT:

- `/prop`
- `/prop_report`
- `/prop_pause`
- `/prop_resume`

Instalar Prop/CFT en VM pausado:

```bash
bash deploy/setup_prop_cft_paper.sh
sudo systemctl restart matibot
```

Instalar y activar Prop/CFT paper:

```bash
ENABLE_PROP_CFT=true bash deploy/setup_prop_cft_paper.sh
sudo systemctl restart matibot
```

## 7. Validacion antes de seguir

```bash
python -m pytest -q
python tools/prop_cft_status.py
python main.py status
```

Ultima validacion local:

```text
233 passed
```

## 8. Siguiente paso recomendado

1. Hacer `git pull origin main` en el otro PC.
2. Verificar que la VM sigue viva con Telegram `/status` y `/health`.
3. Si se quiere continuar Prop/CFT: activar paper, no comprar challenge.
4. Resolver la frescura del cache funding en la VM antes de `accumulation` (~2026-10-07).
5. Mantener v5 como control; no promover un sucesor de v6 sin evidencia forward diferenciada.

## 9. Riesgos pendientes

- El cache funding de Bybit devuelve 403 desde la IP de la VM; sin cache fresco v6 degrada a v5.
- `docs/prop/hyrotrader-plan.md` esta en el limite de 800 lineas. No seguir ampliandolo; crear docs nuevos.
