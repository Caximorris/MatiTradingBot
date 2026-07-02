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
├── data/runtime/paper_state.json     → portfolio paper (balances simulados)
├── data/runtime/swing_rebalances.jsonl → cada rebalanceo ejecutado (fuente de /report y F19)
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

| Quiero... | Como |
|---|---|
| Estado (vivo?, % BTC, valor) | Telegram `/status` (o SSH: `python main.py status`) |
| Informe de rebalanceos | Telegram `/report` o `/report 25` |
| Pausar a distancia | Telegram `/pause` (proceso sigue; no decide) |
| Reanudar | Telegram `/resume` |
| Aviso de cada rebalanceo | Automatico (alerta Telegram) |
| Resultado paridad diaria | Automatico 12:10 UTC (alerta especial si PARITY_FAIL) |
| Logs en vivo | SSH: `journalctl -u matibot -f` |
| Parada total (kill switch) | SSH: `python main.py stop` (deshabilita bots; re-enable para retomar) |
| Apagar/encender el servicio | SSH: `sudo systemctl stop|start matibot` |

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
- [ ] Cuenta cloud creada (Oracle/GCP) — la crea Matias (pide tarjeta, no cobra)
- [ ] Bot de Telegram creado (@BotFather) + chat id
- [ ] VM instalada (`deploy/install_vm.sh` completo, servicios verdes)
- [ ] Smoke 24h (F13) superado — fecha inicio 30 dias: ____
- [ ] 30 dias de paridad (F15) — sin PARITY_FAIL desde: ____
- [ ] F19 sin alertas al cierre de la ventana
- Incidencias/pausas: (anotar fecha y motivo)
