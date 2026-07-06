# REFACTOR_BACKLOG.md — Limpieza y refactor (post-paper)

> Creado 2026-07-06. La optimizacion de tokens por turno YA se hizo (recorte de SESSION.md
> 29KB→8KB). Esto es el backlog de limpieza/refactor de CODIGO, que espera a que cierre la
> validacion paper (F13 24h + F15 paridad 30d) para no romper el determinismo del camino live.
> Decisiones tomadas 2026-07-06: (1) adaptive/scalp/range_reversion SE MANTIENEN registradas como
> baselines; (2) refactor del nucleo se DIFIERE hasta cerrar el paper.

## Ya hecho (2026-07-06, riesgo cero)
- SESSION.md recortado (historia migrada a SESSION_ARCHIVE.md, snapshot integro al final del archive).
- Backup temporal borrado. Verificado: sin junk trackeado, `.gitignore` cubre __pycache__/.pytest_cache.
- Inventario de codigo muerto realizado (abajo).

## Arquitectura — lo que YA es escalable (NO reconstruir)
- `strategies/registry.py` + `base_strategy.py`: anadir estrategia = crear archivo + 1 bloque
  `StrategyMeta`. Carga diferida (importlib), no infla arranque. main.py no se toca. 7 motores enganchados.
- Datos: `data/cache` + pipeline funding (`tools/funding_refresh.py`) + contextos modulares
  (macro/market/funding). Anadir fuente = nuevo modulo de contexto.
- Telegram: `tools/telegram_remote.py` (orquestacion: red/DB/loop + handlers) + `tools/tg_views.py`
  (formateo HTML puro) + `tools/paper_bots.py` (capa de datos multi-bot: rutas/etiquetas/filtros).
  Anadir comando = nuevo handler; anadir vista = funcion pura en tg_views. Multi-bot descubierto
  dinamicamente desde BotState (sin hardcodear bots).
- La tarea de "escalabilidad" es DOCUMENTAR estos 3 puntos de extension, no construir nada.

## Codigo muerto confirmado (borrable, git lo preserva)
- `execution/order_manager.py` — 0 referencias en todo el repo (ni tests). Capa de ejecucion live
  temprana, superseeded por el runtime actual del bot. **Pendiente OK de Matias para borrar.**
- `execution/position_tracker.py` — idem, 0 referencias. **Pendiente OK.**
  (Verificar antes de borrar si se quieren como base para el modo live real futuro.)

## Reorganizacion diferida (requiere auditar referencias — cron VM + skills usan rutas)
- `tools/` (34 scripts): separar operativos de research. NO mover sin auditar `deploy/daily_checks.sh`,
  skills y hooks que invocan por ruta (`funding_refresh`, `swing_parity_check`, `degradation_report`,
  `journal_summary`, `tg_*`, `swing_paper_setup`, `prop_cft_setup`, `swing_chart`).
  - Operativos (NO mover): los de arriba + `tg_send`, `tg_views`, `tg_charts`, `paper_bots`
    (importados por `telegram_remote` en la VM).
  - Research one-off (mover a `tools/research/`): `prop_phase_matrix`, `prop_breach_audit`,
    `prop_challenge_sim`, `prop_phase_frontier`, `prop_router_vs_swing`, `bybit_public_cost_probe`,
    `alpha_screens`, `sens_phases`, `bootstrap_equity`, `stress_usdt_depeg`, `swing_benchmarks`,
    `swing_v5_freeze_report`.
- Docs raiz (14 archivos): mover a `docs/archive/` los historicos/supersedidos
  (`PLAN_MEJORA_AUDITORIA` COMPLETADO, `AUDITORIA_SWING_V4` supersedido por V5). Actualizar punteros
  en SESSION.md. Valor bajo: los docs YA no se cargan por turno, es solo cosmetico.

## Refactor del nucleo (SOLO post-paper, con red de tests + smoke de ancla en verde cada paso)
- `strategies/pro_trend.py` (1856 lineas) viola el limite de 800 PERO esta CONGELADO — no tocar.
- `core/backtest.py` (1153), `core/exchange.py` (771): candidatos a partir pero son el camino live.
  Cualquier deriva mueve las anclas ($9.164M / -52.73%) e invalida la paridad F15. Regla dura:
  cada paso corre la suite completa + smoke de ancla; si el ancla se mueve, se revierte.
- `strategies/scalp_momentum.py` (1106): fuera del roadmap, se puede simplificar sin urgencia.

## Regla de oro de esta limpieza
Proyecto de research: casi todo el "codigo muerto" ES informacion (una hipotesis medida y rechazada).
Sesgo = ARCHIVAR/MOVER, no borrar. Borrado real solo para basura genuina (backups, caches, orfanos
verificados sin valor futuro).
