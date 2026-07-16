# Handoff 2026-07-14 — MatiTradingBot

Este archivo es el punto de arranque para continuar mañana desde otro PC.

> **ESTADO ACTUAL:** trabajar sobre `main`. Swing v6-2 es el default congelado; v5 queda como
> control/rollback historico. El cliente OKX Demo y el fleet de dos bots (v6 + Demo) estan
> desplegados y verificados en la VM; **Prop/CFT se RETIRO de la fleet activa el 2026-07-14**
> (gate de adopcion invalidado por un bug de funding — ver SESSION.md y EXPERIMENTS.md EXP-013).
> El estado operativo y los siguientes pasos viven en `SESSION.md`. Commit de sincronizacion
> inicial: `7d61ca5`; este handoff se mantiene actualizado para continuar desde otro PC.

## 1. Estado rapido

- Rama de trabajo: `main`.
- Default de estrategia: **Swing Allocator v6-2**, congelado.
- Paper fleet: v6 simulado + v6 OKX Demo, activos en VM GCP `matitrbot`, con Telegram y checks
  diarios; legacy/v5 se retiraron del registro, conservando rollback e historial.
- **Prop/CFT: RETIRADO de la fleet activa (2026-07-14).** Su promocion a "candidato vivo"
  (74.8% pass / 2.0% breach) se calculo con `model_funding=True` roto (bug real en
  `load_funding()`, settlements sin ordenar — nunca se aplicaba). Corregido y re-corrido:
  **45.4% pass / 14.8% breach**, no cumple el gate (>=60%). No se compro challenge (sin riesgo
  de capital real). Pendiente en la VM: pull + `tools/paper_fleet_setup.py` + restart para
  desactivar `prop_swing_btc_usdt` (se preserva, no se borra). Ver `EXPERIMENTS.md` EXP-013,
  `docs/prop/hyrotrader-plan.md`.
- Swing v5: control paper y rollback exacto (`use_phase_policy_router=false`,
  `use_funding_overlay=false`).
- **Via "capital ocioso" CERRADA con medicion (2026-07-14, mas tarde ese dia):** EXP-016
  (short de calendario en bear_onset) rechazado en fase de idea; EXP-017 (yield/treasury
  sobre el stable) parked — earn USDC EEA rinde ~1.6-1.8% neto hoy (bajo gate), y
  `tools/delay_sensitivity_replay.py` midio que retrasar solo BUYs cuesta -3.1 a -3.8pp
  CAGR (mata parking off-exchange y sweep manual). Unica llave de reapertura: re-medir
  APR al go-live (sept 2026). Colateral operativo: retraso simetrico 24h = -0.15pp (una
  caida total del bot es barata; la asimetria vender-si/comprar-no es lo letal).
  Detalle: `docs/income/plan.md` Via E.
- Tests al cierre: `272 passed`.
- Verificacion VM 2026-07-14 (antes del retiro de Prop): tres heartbeats recientes, wallet Prop
  persistida en 10,000 USDT, Demo reconciliado 58.0% → 19.2% BTC y `anomaly-check` sin anomalias.

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

- F13: smoke 24h de VM (ventana aun en observacion).
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

### Prop/CFT operativo (RETIRADO de la fleet activa 2026-07-14 — ver arriba)

- `core/cft_monitor.py`: monitor CFT con estado en `data/runtime/prop_cft_status.json`.
- `strategies/prop_swing.py`: persistencia live/paper de posicion/dia/funding idx en BotState
  `prop_swing`; journal operativo `data/runtime/prop_live_journal.jsonl`; hard-stop CFT.
- `tools/prop_cft_setup.py`: registra bot PropSwing CFT paper (manual, ya no via fleet setup).
- `tools/paper_fleet_setup.py`: deja activo exactamente v6 simulado + v6 OKX Demo; **desactiva
  Prop Firm** (retirado 2026-07-14, gate de adopcion invalido) ademas de legacy/v5, sin borrar
  historicos ni wallets.
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
  en cartera simulada y cuenta OKX Demo. El registro v5 se retiró, preservando su rollback.

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

Ultima validacion local (2026-07-14, tras retirar Prop y anadir basis_carry/mr_regime):

```text
272 passed
```

## 8. Siguiente paso recomendado

1. **Pull + `tools/paper_fleet_setup.py` + restart en la VM para desactivar Prop** (pendiente,
   ver seccion 1). Luego mantener v6 + Demo corriendo y revisar `/status`, `/audit` y el
   heartbeat diario.
2. Cerrar F13 (24h), F15 (30d) y F19 para v6/demo; no interpretar la ausencia de trades como
   fallo del allocator.
3. Antes de `accumulation`, desplegar la variante forward OKX: refrescar con
   `python tools/funding_refresh.py --source okx --stale-hours 26`, ejecutar el reconciliador de
   fleet y reiniciar los servicios. El snapshot OKX es forward-only y no re-certifica el ancla
   histórica v6-2 basada en Bybit.
4. Mantener v5 como rollback documentado; no promover un sucesor de v6 sin evidencia forward
   diferenciada. Prop queda retirado — no re-evaluar sin una config que supere el gate corregido.

## 9. Riesgos pendientes

- Bybit devuelve 403 desde la IP de la VM. La sustitución operativa preparada es el snapshot de
  settlements finales de OKX (`funding_overlay_source=okx`); no es una equivalencia histórica con
  Bybit, porque la API pública de OKX tiene cobertura corta. Con el overlay habilitado, un snapshot
  ausente o stale aborta la corrida de forma explícita, no degrada a v5 ni a funding neutral.
- `docs/prop/hyrotrader-plan.md` esta en el limite de 800 lineas. No seguir ampliandolo; crear docs nuevos.
- Verificar si el bot Prop (antes de su retiro) mantuvo algun short en la VM desde su despliegue
  (2026-07-11) — su equity/DD en ese tramo no reflejaria funding real (mismo bug, ver EXP-013).
