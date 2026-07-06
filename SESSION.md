# SESSION.md — Estado del proyecto (HOT — se carga en cada sesion via @SESSION.md)

Complemento de CLAUDE.md. **Deliberadamente corto** para no gastar tokens en cada arranque.
El detalle historico (logs de sesion, tablas de backtest, referencia por modulo, prop/Hyro,
bloques HECHO/Descartado de sesiones 12-18) vive en **`SESSION_ARCHIVE.md`** — leelo BAJO DEMANDA.

**Ultima actualizacion: 2026-07-06** (Swing v6 + aislamiento paper + pipeline funding — MERGEADO A MAIN;
control remoto Telegram multi-bot `6e95f0d`)

---

## ESTADO ACTUAL

**DEFAULT VIGENTE: Swing Allocator v5 post-audit — CONGELADO** (tag `swing-v5-frozen` @ 4c955fb).
v5 = v4 estructural + `daily_on_closed_only=True` (unico delta de comportamiento). Rollback a v4:
`--config '{"daily_on_closed_only": false}'`. Anclas (dataset canonico 102931 velas):
- 2015-26 realistic: **$9.137M | CAGR +85.84% | Max DD -52.73% | 70 reb | btc_vs_bnh 0.8171**
- 2018-26 realistic: $219.8k | +47.14% | -53.72% | 53 | 0.8432
- 2015-26 conservative: $8.897M | +85.40% | -52.88% | 70 | 0.7961
- NOTA smoke: anclas de arriba son via `tools/swing_v5_freeze_report.py`. El CLI (`main.py backtest`)
  da **$9.164M / +85.9%** en 2015-26 realistic (96930 velas vs 96907 del tool; +0.29% USD por warmup,
  NO regresion; DD/ratio/reb identicos). Smoke por CLI compara vs $9.164M; por tool vs $9.137M.

**Swing v6 — NO ADOPT** (`NEEDS_MORE_VALIDATION`, ver `SWING_V6_PLAN.md`). Todo v6/prop entra tras
flags default `False`; main sigue siendo v5 intacto. v6 = phase router (v5_equiv exacto) + funding
overlay que SOLO dispara en fase `accumulation`. Hoy estamos en `bear_onset` (807d post-halving) →
**v6 ≡ v5 en vivo hasta ~2026-10-07** (dia 900); el paper v5-vs-v6 solo divergira desde entonces.

**PAPER DESPLEGADO** — VM GCP e2-micro us-central1 (free tier), Debian 13, VM `matitrbot`. Los 3 bots
en paper con carteras aisladas (`paper_state_<id>.json`; v5 legacy sigue en `paper_state.json`).
Control remoto Telegram **multi-bot** (2026-07-06, commit `6e95f0d`): descubre los bots swing desde
BotState y los distingue por etiqueta (v5/v6/legacy). `/status` resume todos; `/status|/report|/equity
<bot>` apuntan a uno; `/bots` lista carteras. Alertas de rebalanceo y heartbeat por bot. Prop sigue en
`/prop`. Capa pura en `tools/paper_bots.py` + `tools/tg_views.py` (telegram_remote 674 lineas <800).
Operacion normal = leer heartbeat + check diario; consola innecesaria. Runbook: `DEPLOY_PAPER.md`.
Smoke F13 (24h) y paridad F15 (30d) corriendo desde 2026-07-04. Tests 153/153.

**Pro Trend v13 — PAUSADO INDEFINIDAMENTE** (decision sesion 14). Codigo congelado y reversible,
fuera del roadmap activo. Framework de validacion estaba completo. Detalle en archive.

---

## REGLAS INVARIANTES ANTES DE TOCAR CODIGO

Prioridad sobre cualquier optimizacion. Un cambio que no las cumpla NO pasa a default aunque mejore
un backtest puntual.

### 1. Lookahead bias — tolerancia cero
- Dato diario/semanal/4H usado intradia debe estar CERRADO antes del tick. No usar vela/semana/bloque
  4H en curso.
- Externos con offset conservador: MVRV/CoinMetrics = dia anterior; DXY/NDX/VIX/Yahoo = sesion anterior;
  Funding OKX = dia completo anterior.
- Indicador nuevo: documentar en codigo que timestamp representa y por que no mira futuro. Ante duda,
  asumir que el dato NO estaba disponible y desplazarlo.

### 2. Overfitting — protocolo obligatorio
- No promover un cambio que solo mejora 2018-2026 o que elimina un unico trade perdedor.
- Ventana principal BTC: **2015-01-01 a 2026-01-01** (mas trades, 3 ciclos). 2018-2026 = secundaria.
- Comparar candidatos por **CAGR y Max DD** (anclas estables); PF como rango, NO como ancla (es fragil
  al punto de inicio). Fijar siempre inicio 2015.
- Cada cambio se testea AISLADO contra baseline y luego combinado solo si aporta por separado.
- Coste minimo `--costs realistic`; candidatos finales tambien `conservative`.
- Threshold nuevo necesita justificacion ESTRUCTURAL, no "porque arregla T6/T8/T9".
- Si sube CAGR pero empeora mucho PF/MaxDD → variante agresiva, no default.

### 3. Preservar rollbacks
- No sobrescribir ni borrar journals existentes. Todo cambio nuevo debe ser reversible por config.
- Rollback conceptual Pro Trend v13: `partial_exit_pct=150.0`, `partial_exit_size=0.33`,
  `entry_score_min=9`, `adx_min_entry=15.0`, `trailing_stop_pct=0.22`, `trailing_stop_pct_bull=0.28`,
  `cooldown_atr_stop_days=30`, `macd_exit_enabled=False`, `allow_shorts=False`,
  `disable_external_filters=False`.
- Swing v1/v2 config exactas: ver "SWING ALLOCATOR — REFERENCIA" en SESSION_ARCHIVE.md.

### 5. Out-of-sample — ventana 2015-2026 CERRADA para optimizacion (auditoria 2026-07-02)
- Ningun cambio de estrategia se adopta por mejorar 2015-2026. Esa ventana solo se usa para MEDIR
  robustez/sensibilidad de lo ya adoptado. La evidencia para cambios futuros = datos posteriores a
  2026-01-01 (forward/paper) o justificacion estructural pura + no-empeora-anclas.
- Excepcion permitida: SIMPLIFICACION (quitar componentes) si no empeora las anclas.

### 4. Determinismo de datos
- Backtests deterministas via cache OHLCV (`data/cache/`). Runs con rango cacheado = velas identicas.
- Resultado SENSIBLE al punto de inicio (dataset canonico: 102931 velas; viejo 96906). El cache OHLCV
  esta VERSIONADO en git (restaurable con `git checkout`). Las herramientas de reporte clampan al rango
  del cache y NO re-descargan (incidente 2026-07-06 restaurado, ver nota CLAUDE.md). No mezclar caches
  entre maquinas.
- Backtests CONTINUOS — nunca reiniciar balance en frontera de año/mes.

---

## SIGUIENTE PASO

Optimizacion de backtest del Swing = **CERRADA** (v5 default, frente de Max DD agotado — es el suelo
estructural de long-only ~100% en mercado, ver archive). Proximo hito = **validacion forward / paper
trading**: cerrar F13 (smoke 24h), F15 (paridad 30d) y F19 (datos de degradacion). `start` en vivo
requiere confirmacion explicita. El paper v5-vs-v6 empieza a dar señal desde ~2026-10-07.

---

## PENDIENTES ABIERTOS (todos cerrados/parqueados — NO reabrir sin evidencia nueva)

- **Max DD Swing (-52.73%):** frente CERRADO (sesion 15). Suelo estructural; nace en bull_peak y
  accumulation/COVID, NO en bear_onset. Todo lever probado agota CAGR o es inerte.
- **Q4 2025 ping-pong:** residual estructural, sin via viva. Descartados cooldown=7d, ADX gate,
  cap-bear_onset. Detalle en archive.
- **Pro Trend bugfixes candidatos** (P1, sin backtest aislado): fix MACD 4H key, fix VIX sizing cap.
- **Limpieza/refactor de codigo:** backlog en `REFACTOR_BACKLOG.md`. Difiere al cierre del paper
  (no romper determinismo/paridad). Codigo muerto confirmado: `execution/order_manager.py` +
  `position_tracker.py` (0 refs, pendiente OK para borrar).
- **Descartado y NO reintentar:** latch del cap, regime_delta 0.15, VIX, MVRV, Pi Cycle, floor<0.20,
  global max_btc_pct cap, ATR intradia, halving_only, clock_aligned_cadence, fill_next_open.

---

## PUNTEROS A REFERENCIA (leer bajo demanda, NO precargar)

- `HANDOFF_2026-07-05.md` — doc principal para continuar en otro PC (branch, setup, estado operativo,
  Prop/CFT, Swing v6, tests, siguientes pasos).
- `DEPLOY_PAPER.md` — runbook y estado del despliegue paper en la VM.
- `SWING_V6_PLAN.md` — plan v6 (phase router + funding overlay; criterios de promocion Fase 4).
- `SWING_PLAN.md` / `AUDITORIA_SWING_V4.md` / `AUDITORIA_SWING_V5_POST_IMPLEMENTACION.md` /
  `PLAN_MEJORA_AUDITORIA.md` (F1-F19) — diseño, auditorias y plan del Swing.
- `HYROTRADER_PLAN.md` — estrategia prop firm (Bybit/CFT/Hyro). Estado: motor `funding_extreme` da
  edge standalone real (PF 1.44, DD 13%) pero RECHAZADO como prop (gate two-step ~27% pass / 37%
  breach vs >=60%/<=20%). Router CFT-only (`entry_halving_phases=bear_onset,accumulation`) es el mejor
  candidato pero requiere validar reglas reales CFT/Match/MT5 — sin confirmacion escrita, NO comprar.
- `SESSION_ARCHIVE.md` — logs sesiones 12-18, auditorias, resultados backtest, referencia por modulo,
  detalle prop/Hyro, bloques HECHO/Descartado migrados.
- `backtests/STRATEGY_VERSIONS.md` — historial de versiones.
- Journals: NO hacer `Read` del JSON crudo (>10 MB). Usar `python tools/journal_summary.py <ruta>`
  o `/journal-summary`.

---

## DONDE ESTA CADA COSA (referencia rapida)

- Estrategias: `strategies/pro_trend.py`, `swing_allocator.py`, `adaptive_trend.py`,
  `scalp_momentum.py`, `prop_swing.py`, `funding_extreme.py`. Indicadores: `strategies/indicators.py`.
- Contexto externo: `macro_context.py` (MVRV+halving), `market_context.py` (DXY/NDX/VIX),
  `funding_context.py`. Overlay v6: `swing_funding_overlay.py`.
- Backtest: `core/backtest.py`. Cache: `data/ohlcv_cache.py`. Prop: `core/prop_rules.py`,
  `core/cft_monitor.py`. Journals: `reporting/trade_journal.py`, `reporting/swing_journal.py`.
- Umbrales y config detallada de cada modulo: SESSION_ARCHIVE.md.
