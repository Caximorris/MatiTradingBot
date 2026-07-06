# DEPLOY_PAPER.md — Paper trading del Swing v5 en la nube (runbook)

Plan aprobado 2026-07-02 (sesion 16). Objetivo: correr la validacion forward del Swing v5
(smoke 24h F13 + paridad 30 dias F15 + degradacion F19) en una VM gratuita, con control
remoto por Telegram, sin depender del PC de casa. Coste objetivo: $0.

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
├── data/runtime/paper_state.json     → portfolio paper del bot legacy (sin paper_portfolio_id)
├── data/runtime/paper_state_<id>.json → portfolio paper de cada bot aislado (swing_v6, prop_cft...)
├── data/runtime/swing_rebalances.jsonl → cada rebalanceo (tag `strategy` por bot; fuente /report y F19)
└── data/runtime/daily_checks.log     → historial de checks diarios
```

Claves de diseno:
- **Paper = sin secretos**: no hay API keys de OKX en la VM (solo datos publicos de mercado).
  El unico secreto es el token del bot de Telegram (da acceso a pausar/reanudar, nada mas).
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

## Operacion diaria

> **Multi-bot (v5/v6/legacy):** cada bot swing con `paper_portfolio_id` tiene su cartera
> aislada (`paper_state_<id>.json`) y el control remoto los distingue. `/status` sin argumento
> resume TODOS; `/status <bot>`, `/report <bot>`, `/equity <bot>` apuntan a uno. `/bots` lista
> los registrados y su etiqueta (v5/v6/legacy). Prop sigue en su propio `/prop`.

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

## Prop/CFT paper en la misma VM

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
- [ ] Smoke 24h (F13) — corre desde 2026-07-04 08:58 UTC; revisar journalctl 2026-07-05.
      Superado: ____ — fecha inicio 30 dias: ____
- [ ] 30 dias de paridad (F15) — sin PARITY_FAIL desde: ____
- [ ] F19 sin alertas al cierre de la ventana
- Incidencias/pausas: (anotar fecha y motivo)
