# DEPLOY_PAPER.md — v6-2 simulado + v6-2 OKX Demo (runbook)

Topologia vigente desde 2026-07-14 (tarde): **dos** bots activos en una VM gratuita:
Swing v6-2 simulado y Swing v6-2 con ejecucion OKX Demo. Legacy se retira del registro;
v5 tambien se retira pero conserva historial, wallet y estado para rollback.

**Prop Firm/CFT (`prop_swing_btc_usdt`) RETIRADO de la fleet activa 2026-07-14.** Su
promocion a "candidato vivo" (74.8% pass / 2.0% breach, `docs/prop/hyrotrader-plan.md`)
se calculo con un bug real: `load_funding()` devolvia los settlements de funding SIN
ordenar, asi que `model_funding=True` nunca se aplicaba (ver EXPERIMENTS.md EXP-013).
Corregido y re-corrido: **45.4% pass / 14.8% breach — no cumple el gate de adopcion
(>=60%)**. `tools/paper_fleet_setup.py` ya no lo incluye en `desired_fleet()`; correrlo
tras el pull DEACTIVA `prop_swing_btc_usdt` (no lo borra — wallet, journal y BotState se
preservan para auditoria/rollback, igual que v5).

**Accion requerida en la VM tras el proximo `git pull`:**
```bash
.venv/bin/python tools/paper_fleet_setup.py
sudo systemctl restart matibot
```
Sin este paso, la mera actualizacion de codigo (`/update` = pull + restart) NO desactiva
el bot por si sola — `paper_fleet_setup.py` no se auto-ejecuta en cada restart, solo en
la instalacion inicial (`deploy/install_vm.sh`). El comando es idempotente y seguro de
repetir.

Estado verificado 2026-07-14 (antes del retiro de Prop): `main` en la VM ya contenia el
fleet setup; los tres bots tenian ticks recientes, `paper_state_prop_cft.json` existia
con 10,000 USDT iniciales, Demo quedó reconciliado mediante un evento auditable
`RECONCILE`, y `main.py anomaly-check` no reportaba anomalias. Desde aqui, con Prop
retirado, solo quedan v6 simulado y v6 Demo; F13/F15/F19 siguen aplicando a esos dos.

**Este documento es el punto de reanudacion**: si el proyecto se pausa, aqui esta todo lo
necesario para retomar exactamente donde quedo (ver "Estado del despliegue" al final).

---

## Arquitectura

```
VM Linux gratuita (Oracle Free / GCP e2-micro)
├── systemd matibot.service           → python main.py start   (Restart=always)
├── systemd matibot-telegram.service  → tools/telegram_remote.py (control remoto)
└── cron 12:10 UTC                    → deploy/daily_checks.sh (paridad F15 + degradacion F19)

Estado persistente (sobrevive a reinicios de proceso y de VM):
├── trading.db                        → BotState: is_active, estado del Swing (initialized,
│                                        last_rebalance, last_eval_block)
├── data/runtime/paper_state_<id>.json → portfolio paper de cada bot aislado (swing_v6, prop_cft...)
├── data/runtime/swing_rebalances.jsonl → cada rebalanceo (tag `strategy` por bot; fuente /report y F19)
└── data/runtime/daily_checks.log     → historial de checks diarios
```

Claves de diseno:
- **Paper local = sin claves de trading**: v6 simulado y Prop Firm solo usan datos publicos.
  La instancia `demo` usa una API key exclusiva de OKX Demo y Telegram usa su propio token;
  ninguna clave permite operar capital real.
- **`OKX_SANDBOX=false` obligatorio**: datos del exchange real. El sandbox demo tiene precios
  propios y romperia la paridad con el backtest. Paper nunca envia ordenes reales.
- **Telegram por long-polling**: sin puertos abiertos en la VM, solo trafico saliente.
  Solo responde al `TELEGRAM_CHAT_ID` configurado.
- **Pausar NO mata el proceso**: es el flip de `is_active` en DB que el scheduler consulta
  en cada tick (`main.py:526-530`). El proceso sigue vivo y reanudar es instantaneo.

## Eleccion de VM (decidido)

1. **Oracle Cloud Always Free** (preferida): ARM A1 (hasta 4 CPU/24GB) o AMD micro. Gratis
   para siempre. Pegas: registro con tarjeta, capacidad ARM variable por region, y reclaman
   instancias "idle" en Always Free — mitigar convirtiendo la cuenta a Pay-As-You-Go (sigue
   sin cobrar si no excedes el tier gratuito).
2. **GCP e2-micro** (alternativa): us-west1/us-central1/us-east1, 1GB RAM (el instalador
   anade 1G de swap), gratis para siempre, registro mas fiable.
3. **Hetzner CX22 ~4 EUR/mes**: plan B de pago si los gratuitos fallan.
4. **Descartados**: Render/Railway/Fly free (matan procesos largos).

## Instalacion (una vez creada la VM Ubuntu 22.04/24.04)

```bash
# 1. En Telegram: crear bot con @BotFather (token) y obtener tu chat id con @userinfobot
# 2. En la VM:
git clone https://github.com/Caximorris/MatiTradingBot.git && cd MatiTradingBot
bash deploy/install_vm.sh        # 1a pasada: crea .env y pide editarlo
nano .env                        # rellenar TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID
bash deploy/install_vm.sh        # 2a pasada: bot enable + systemd + cron
```

Verificacion inmediata: mensaje "Control remoto conectado" en Telegram, y
`journalctl -u matibot -f` mostrando el tick del scheduler.

## Topologia deseada e idempotente

```bash
.venv/bin/python tools/paper_fleet_setup.py
```

El comando activa exactamente `swing_allocator_v6_btc_usdt` y
`swing_allocator_demo_btc_usdt`; elimina registros legacy/v5, desactiva cualquier otro
bot operable (incluido `prop_swing_btc_usdt` desde 2026-07-14, ver arriba) y preserva
wallets, journals y filas internas de estado.

## Operacion diaria

> **Multi-bot (v6/demo/prop):** cada bot con `paper_portfolio_id` tiene su cartera
> aislada (`paper_state_<id>.json`) y el control remoto los distingue. `/status` sin argumento
> resume TODOS; `/status <bot>`, `/report <bot>`, `/equity <bot>` apuntan a uno. `/bots` lista
> los registrados y su etiqueta (v6/demo). Prop también aparece en `status`/`audit` y conserva
> sus controles `/prop`.

Telegram muestra un panel persistente con botones para las acciones de lectura habituales:
resumen, detalle v6/demo, Prop, auditoria, salud, reports, equity, grafico BTC, senales y paridad.
No hace falta escribir argumentos. `/menu` recupera el panel si se oculta. Las acciones que cambian
estado (`/pause`, `/resume`, `/restart`, `/update`, controles Prop) quedan fuera del panel para
evitar pulsaciones accidentales y siguen disponibles en el menu de comandos de Telegram.

| Quiero... | Como |
|---|---|
| Resumen de todos los bots | Telegram `/status` |
| Lista de bots y su cartera | Telegram `/bots` |
| Estado de un bot (vivo?, % BTC, vs B&H) | Telegram `/status v6` (o SSH: `python main.py status`) |
| Informe de rebalanceos de un bot | Telegram `/report v6` o `/report v6 25` |
| Grafico equity bot vs B&H | Telegram `/equity v6` o `/equity v6 45` (2-60 dias) |
| Grafico precio + rebalanceos | Telegram `/chart [bot] [dias]` |
| Target y senales AHORA (calculo live) | Telegram `/signals` (~1 min; corre parity check) |
| Paridad F15: ultimo check y racha /30 | Telegram `/parity` (lee daily_checks.log) |
| Salud VM (servicios, RAM, disco, errores) | Telegram `/health` |
| Red-flags de infra/datos/estado (incl. cron viejo) | Telegram `/audit` (= CLI `anomaly-check`) |
| "Por que rebalanceo?" en lenguaje llano | SSH: `python main.py explain --bot v6` |
| Reconciliar una correccion Demo fuera del journal | SSH: `python main.py reconcile-demo-journal` |
| Logs sin SSH | Telegram `/logs` o `/logs 100` |
| Backup DB+estado al chat | Telegram `/backup` (ademas automatico semanal) |
| Reiniciar el bot sin SSH | Telegram `/restart` |
| Actualizar codigo sin SSH | Telegram `/update` (git pull --ff-only + restart) |
| Pausar a distancia | Telegram `/pause` (proceso sigue; no decide) |
| Reanudar | Telegram `/resume` |
| Estado Prop/CFT | Telegram `/prop` |
| Eventos PropSwing | Telegram `/prop_report` o `/prop_report 50` |
| Pausar PropSwing | Telegram `/prop_pause` |
| Reanudar PropSwing | Telegram `/prop_resume` |
| Aviso de cada rebalanceo | Automatico (alerta Telegram) |
| Caida del proceso (sin tick >10 min) | Automatico (watchdog Telegram, alerta y recuperacion) |
| "Sigue vivo?" sin preguntar | Automatico (heartbeat diario 08:00 UTC) |
| Resultado paridad diaria | Automatico 12:10 UTC (alerta especial si PARITY_FAIL) |
| Logs en vivo | SSH: `journalctl -u matibot -f` |
| Parada total (kill switch) | SSH: `python main.py stop` (deshabilita bots; re-enable para retomar) |
| Apagar/encender el servicio | SSH: `sudo systemctl stop|start matibot` |

`python main.py status` no usa ya el `paper_state.json` legacy como balance global: muestra una
fila por cartera operable, separa señal de ejecucion, convierte el ultimo tick a Europe/Madrid y
etiqueta Demo como `BTC-USDC`/USDC. Las filas internas de persistencia quedan ocultas.

En Telegram, Demo muestra `valoracion hibrida` en vez de bot/B&H: los fills del motor Demo divergen
del spot real usado para valorar, asi que ese salto no es PnL. `/equity demo` queda bloqueado si la
serie no es comparable. `/audit` alerta `journal-allocation-gap` cuando la cartera actual difiere
mas de 15pp del ultimo evento, por ejemplo tras una correccion manual fuera del journal. Las horas
de datos, rebalanceos, checks y proximas evaluaciones se muestran en Europe/Madrid; la programacion
interna y la DB permanecen en UTC.

Tras una correccion Demo ejecutada manualmente fuera de la estrategia, correr una vez:

```bash
.venv/bin/python main.py reconcile-demo-journal
.venv/bin/python main.py anomaly-check
```

El primer comando no opera ni reescribe historia: anexa un evento `RECONCILE` con el motivo,
snapshot exacto de BTC y el alias USDT del efectivo USDC, mas un fingerprint idempotente.
Repetirlo sobre el mismo snapshot no anade
otra linea. `anomaly-check` incluye tambien Prop; las carteras simuladas nuevas escriben su balance
inicial de 10,000 USDT al arrancar, antes del primer trade.

## Prop/CFT paper en la misma VM

**RETIRADO de la fleet activa 2026-07-14** (ver nota al inicio de este documento — gate
de adopcion no cumplido tras corregir el bug de funding). Esta seccion describe la
operativa de cuando estaba activo; se conserva por si se re-evalua un candidato
corregido en el futuro (`deploy/setup_prop_cft_paper.sh` sigue disponible para
re-registrarlo manualmente, fuera de `paper_fleet_setup.py`).

El PropSwing CFT queda separado del Swing:

- `/pause` y `/resume` solo afectan al Swing.
- `/prop_pause` y `/prop_resume` solo afectan al PropSwing.
- El monitor CFT vive en `data/runtime/prop_cft_status.json`.
- El journal operativo vive en `data/runtime/prop_live_journal.jsonl`.
- Los eventos de reglas CFT viven en `data/runtime/prop_cft_events.jsonl`.

Registrar Prop/CFT pausado:

```bash
bash deploy/setup_prop_cft_paper.sh
sudo systemctl restart matibot
```

Registrar y activar Prop/CFT paper:

```bash
ENABLE_PROP_CFT=true bash deploy/setup_prop_cft_paper.sh
sudo systemctl restart matibot
```

Config congelada que instala el script:

```json
{
  "entry_mode": "breakout",
  "risk_per_trade": 0.018,
  "tp1_r": 1.5,
  "allow_shorts": true,
  "max_notional_pct": 0.8,
  "model_funding": true,
  "entry_halving_phases": "bear_onset,accumulation",
  "cft_monitor_enabled": true,
  "cft_account_size": 50000,
  "cft_phase": "p1",
  "cft_daily_dd_pct": 0.06,
  "cft_max_loss_pct": 0.12
}
```

Chequeos:

```bash
.venv/bin/python tools/prop_cft_status.py
.venv/bin/python main.py bot list
```

## Bot demo OKX en la misma VM (pre-live septiembre 2026)

Bot `demo` (uno de los tres activos): misma estrategia v6-2 congelada, pero las ordenes van a la cuenta
DEMO real de OKX (header `x-simulated-trading:1`) via `core/okx_demo_client.py`. Ejercita el
camino de ordenes AUTENTICADO (firma, params, errores) que ningun otro bot toca. El market
data sigue siendo el REAL (flag=0) → la paridad F15 no se ve afectada. Medido 2026-07-11: el
feed de precios demo infla high/low $80-250 por vela 1H — jamas usarlo para señales.

Requisitos (manuales):

1. OKX → cambiar a modo **Demo trading** → crear una API key DEMO (las keys de la cuenta real
   NO funcionan con el header de simulacion).
2. En el `.env` de la VM: `OKX_DEMO_API_KEY`, `OKX_DEMO_SECRET_KEY`, `OKX_DEMO_PASSPHRASE`
   y — para cuentas de la entidad europea (MiCA) — `OKX_DEMO_DOMAIN=https://my.okx.com`
   (sin esa linea la key EEA devuelve error 60032 contra www.okx.com).
3. Cuenta EEA: **no existe USDT** (bloqueado por compliance, sCode 51155). El bot piensa en
   BTC-USDT pero ejecuta en BTC-USDC (`execution_quote: "USDC"` en la config, el balance USDC
   se presenta como USDT). Ideal: cuenta demo con solo USDC; si ya tiene BTC, el bot salta el
   INIT y rebalancea directo en la primera evaluacion 4H. El resto de monedas se ignora.

```bash
.venv/bin/python tools/paper_fleet_setup.py
sudo systemctl restart matibot
sudo systemctl restart matibot-telegram   # OJO: servicio SEPARADO — sin esto /status demo
                                          # no existe y las alertas salen con etiqueta vieja
```

Verificacion: `/bots` muestra el bot `demo`; su cartera se espeja en
`data/runtime/paper_state_okx_demo.json` (espejo read-only del balance en OKX — editarlo no
cambia nada), asi que `/status demo` y `/report demo` leen ese estado. `/equity demo` se bloquea
porque la serie hibrida no es PnL comparable. Si las credenciales demo faltan o son invalidas,
el arranque SALTA solo ese bot
(los otros dos arrancan normal) y lo dice en el log de arranque.

Peculiaridades del entorno demo (medidas 2026-07-13, no afectan al live):

- El motor demo cotiza ~5% por debajo del feed real y el book demo de BTC-USDC tiene los bids
  muertos bajo la banda de precio (sCode 51138): los market SELL se aceptan y se cancelan sin
  fill. Por eso la config lleva `execution_bridge: "EUR"`: la orden cancelada se reintenta en
  2 patas (BTC↔EUR↔USDC, books demo EUR vivos). En el log se ve como `[DEMO-BRIDGE] pata ...`.
- El equity del espejo mezcla fills a precio demo con valoracion a precio real: los saltos de
  portfolio de ±3-5% tras un rebalanceo son ese desfase, NO PnL.
- Smoke manual del camino completo: `.venv/bin/python tools/okx_demo_smoke.py` (solo lectura;
  `--trade` para un ciclo buy/limit-cancel/sell con 0.001 BTC).

## Criterios de cierre (de PLAN_MEJORA_AUDITORIA.md)

- **F13 (smoke 24h)**: 24h sin excepciones en `journalctl -u matibot`, target logueado en
  cada bloque 4H. Si falla algo: arreglar, reiniciar, y el reloj de 30 dias empieza DESPUES.
- **F15 (paridad 30 dias)**: 30 checks diarios consecutivos con `PARITY_OK`. Tolerancia CERO
  (es determinista): un `PARITY_FAIL` = bug = `/pause` + investigar + reiniciar la cuenta de 30.
- **F19 (degradacion)**: `degradation_report.py` sin alertas de frecuencia (>2x backtest,
  ~3.1 rebalanceos/trimestre) ni gap target/after >2pp.
- Expectativa realista de actividad: **2-3 rebalanceos al mes**. Semanas sin operaciones son
  normales y NO indican fallo (verificar vida con /status, no con la ausencia de trades).

## Semantica de pausas y reinicios (que se pierde y que no)

- **Reinicio de proceso/VM (minutos-horas)**: NO se pierde nada. El bloque 4H no evaluado se
  recupera en el siguiente. systemd relanza solo.
- **/pause dias**: el bot no decide mientras tanto; los rebalanceos que "tocaban" no ocurren.
  Para la validacion de 30 dias, una pausa >1 dia ensucia la comparacion: anotarla en la
  seccion de estado de abajo y valorar reiniciar la cuenta.
- **Perdida de la VM**: el portfolio paper y el historial estan SOLO en la VM
  (`trading.db`, `data/runtime/` — gitignored). Backup si preocupa:
  `scp vm:MatiTradingBot/trading.db vm:MatiTradingBot/data/runtime/*.json* ./backup/`
  De serie no hay backup automatico — perder la VM = reiniciar la validacion.

## Troubleshooting

- `/status` dice "ACTIVO PERO SIN TICK HACE X MIN" → el proceso murio y systemd no lo
  relanzo o la VM esta caida: `sudo systemctl restart matibot` / revisar `journalctl`.
- Telegram no responde → `systemctl status matibot-telegram`; el servicio reintenta solo
  ante caidas de red.
- PARITY_FAIL → NO es ruido, es bug por definicion. `/pause`, guardar
  `data/runtime/daily_checks.log`, y depurar comparando senales live vs backtest.
- Oracle recupera la instancia → convertir cuenta a PAYG o migrar a GCP; restaurar backup.

---

## ESTADO DEL DESPLIEGUE (actualizar a mano en cada hito)

- [x] Codigo listo: fixes ruta live (commit b61ea95), telegram_remote + tg_send,
      deploy/ (install_vm.sh, units systemd, daily_checks.sh), tools portables a Linux.
- [x] Cuenta cloud creada: GCP e2-micro us-central1 (free tier), Debian 13, VM `matitrbot`
      (2026-07-04). Disco standard 30GB, sin snapshots, sin Ops Agent.
- [x] Bot de Telegram creado (@BotFather) + chat id (2026-07-04)
- [x] VM instalada (2026-07-04 08:58 UTC): servicios matibot + matibot-telegram verdes,
      /status y /report responden. Fix necesario: DetachedInstanceError en bot enable (9214e1e).
      INIT 0%->60% + SELL 60%->20% (regime_bear,halving_bear_onset) — coincide con parity F15.
- [ ] Smoke 24h (F13) — ventana de observacion iniciada 2026-07-04 08:58 UTC; confirmar el
      cierre en el reporte de forward-test.
- [ ] 30 dias de paridad (F15) — sin PARITY_FAIL desde: **2026-07-11** (racha anterior de 3
      invalidada por el incidente del cron, ver abajo; nunca hubo PARITY_FAIL, solo dias sin medir)
- [ ] F19 sin alertas al cierre de la ventana
- [x] Bot demo OKX registrado y activo (deploy y primer fill verificados 2026-07-13; estado
      operativo confirmado 2026-07-14).
- [x] **Prop Firm/CFT RETIRADO de la fleet activa (2026-07-14).** Gate de adopcion
      corregido (bug de funding, EXP-013) fallo: 45.4% pass vs >=60% requerido. Pendiente
      en la VM: pull + `tools/paper_fleet_setup.py` + `systemctl restart matibot` para
      desactivar `prop_swing_btc_usdt` (BotState/wallet/journal se preservan).
- Incidencias/pausas: (anotar fecha y motivo)
  - **2026-07-07 → 2026-07-11 — cron de daily_checks sin correr (INFRA, contrato 6b).**
    `deploy/daily_checks.sh` perdio el bit +x en el commit `2019859` (2026-07-06); cron
    intentaba ejecutarlo y fallaba EN SILENCIO (sin MTA no hay mail de error; el log de cron
    registra el intento igual). 5 dias sin check de paridad — la estrategia NUNCA fallo, solo
    dejo de medirse. Fix: `973d433` (+x versionado en git) + chmod en la VM. Deteccion añadida
    para que no se repita: alerta `daily-check-stale` en anomaly-check/`/audit` + `/parity`
    marca VIEJO si el ultimo check tiene >26h.
  - **2026-07-06 → 2026-07-11 — bot "prop" corria la estrategia equivocada (INFRA).**
    `strategies/registry.resolve()` casaba por prefijo sin limite de palabra:
    `prop_swing_btc_usdt` resolvia al alias `pro` (pro_trend) → 5 dias corriendo Pro Trend v13
    con config default en vez de PropSwing (0 trades, 0 daño — verificado en DB). Fix `4b1425f`
    (limite `_` + match mas largo + tests). PropSwing real re-arrancado 2026-07-11.
  - **2026-07-09 14:37-15:47 UTC — stall del scheduler (INFRA, autorecuperado).** Un timeout de
    `get_ohlcv` colgo un tick ~70 min (job skips por max_instances=1); se recupero solo y no
    cayo en frontera 4H. Sin accion.
