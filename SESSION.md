# SESSION.md — Estado del proyecto (HOT — se carga en cada sesion via @SESSION.md)

Complemento de CLAUDE.md. **Deliberadamente corto** para no gastar tokens en cada arranque.
El detalle historico (logs de sesion, tablas de backtest, referencia por modulo, prop/Hyro,
bloques HECHO/Descartado de sesiones 12-18) vive en **`docs/archive/session-archive.md`** — leelo BAJO DEMANDA.

**Ultima actualizacion: 2026-07-11** (revision semana 1 del forward-test: 2 bugs de infra
encontrados y ARREGLADOS `973d433`/`4b1425f` pusheados; T5.1 explain + T11.1 EXPERIMENTS.md +
`/audit` + deteccion cron-stale en `7107631` commiteado SIN PUSH; cliente OKX demo trading
construido SIN COMMIT — retomar en "SIGUIENTE PASO")

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

**Swing v6 — NO ADOPT** (`NEEDS_MORE_VALIDATION`, ver `docs/swing/v6-plan.md`). Todo v6/prop entra tras
flags default `False`; main sigue siendo v5 intacto. v6 = phase router (v5_equiv exacto) + funding
overlay que SOLO dispara en fase `accumulation`. Hoy estamos en `bear_onset` (807d post-halving) →
**v6 ≡ v5 en vivo hasta ~2026-10-07** (dia 900); el paper v5-vs-v6 solo divergira desde entonces.

**PAPER DESPLEGADO** — VM GCP e2-micro us-central1 (free tier), Debian 13, VM `matitrbot`. Los 3 bots
en paper con carteras aisladas (`paper_state_<id>.json`; v5 legacy sigue en `paper_state.json`).
Control remoto Telegram **multi-bot** (2026-07-06, commit `6e95f0d`): descubre los bots swing desde
BotState y los distingue por etiqueta (v5/v6/legacy). `/status` resume todos; `/status|/report|/equity
<bot>` apuntan a uno; `/bots` lista carteras. Alertas de rebalanceo y heartbeat por bot. Prop sigue en
`/prop`. Capa pura en `tools/paper_bots.py` + `tools/tg_views.py` (telegram_remote 674 lineas <800).
Operacion normal = leer heartbeat + check diario; consola innecesaria. Runbook: `docs/ops/deploy-paper.md`.
Smoke F13 (24h) y paridad F15 (30d) corriendo desde 2026-07-04. Tests 179/179.

**OBSERVABILIDAD FORWARD-TEST (2026-07-06)** — suite read-only que NO toca la estrategia (plan
`docs/forward-test/research-lab-plan.md`, fases 1-3). Reglas del test congeladas en
`docs/forward-test/contract.md` (inicio 2026-07-04, taxonomia fallo-estrategia vs fallo-infra).
Comandos: `paper-status` (control center v5/v6/legacy), `anomaly-check` (red-flags + Telegram
dedup), `forward-report` (solo datos post-inicio, filtro duro), `data-audit` (integridad OHLCV,
nunca re-descarga). Capa pura: `tools/{paper_snapshot,anomaly_check,forward_report,data_audit}.py`
+ `cli/paper_cmds.py`. **Hallazgo de `data-audit`:** cache canonico tiene 474 filas duplicadas
benignas (identico OHLCV) en el empalme 2017 → 102457 distintas de 102931; NO deduplicar en
forward-test (mutacion de cache prohibida, ver CLAUDE.md). Pendiente: correr la suite EN la VM
(datos paper reales viven alli, no en dev).

**SEMANA 1 DEL FORWARD-TEST (revision 2026-07-11)** — v5/legacy y v6 sanos (ambos target 0.20,
señales identicas `regime_bear,halving_bear_onset`, paridad OK). Dos bugs de INFRA (contrato 6b,
no invalidan la estrategia) encontrados via Telegram+SSH y arreglados:
1. `deploy/daily_checks.sh` perdio el bit +x en el commit `2019859` → el cron fallo EN SILENCIO
   5 dias (2026-07-07→11); `/parity` seguia verde porque solo miraba el ultimo resultado, no su
   antiguedad. Fix `973d433` (+x en git) + deteccion `daily-check-stale` en anomaly_check +
   `/parity` ahora avisa VIEJO. La racha F15 se reinicia ~2026-07-11 (5 dias sin medir).
2. `registry.resolve()` casaba por prefijo sin limite de palabra: `prop_swing_btc_usdt` resolvia
   a **pro_trend** (alias corto `pro`) → el bot "prop" corrio 5 dias como Pro Trend v13 con
   config default (0 trades, cero daño, verificado en DB). Fix `4b1425f` (limite `_` + match mas
   largo + tests). Re-arrancado como PropSwing real el 2026-07-11.
Ademas: `/audit` en Telegram (mismo motor que `anomaly-check`), `main.py explain` (T5.1),
`EXPERIMENTS.md` (T11.1) — todo en `7107631` (SIN PUSH). Suite observabilidad corrida EN la VM
por primera vez: limpia (los 474 dups del cache = hallazgo conocido, no accion).

**CLIENTE OKX DEMO TRADING (2026-07-11) — construido, SIN COMMIT, pendiente deploy.** Objetivo:
ejercitar por PRIMERA vez el camino de ordenes autenticado real de OKX antes del live de
septiembre 2026. `core/okx_demo_client.py` (hibrido: market data REAL flag=0 → paridad F15
intacta; ordenes/balance DEMO flag=1 con credenciales `OKX_DEMO_*`), `tools/okx_demo_setup.py`
(registra `swing_allocator_demo_btc_usdt`, label `demo`, config v5 exacta + `execution=okx_demo`),
routing en `cli/live_cmds.py` (fallo de credenciales = skip solo ese bot). Espejo de balances en
`paper_state_okx_demo.json` → Telegram `/status demo` etc. funcionan sin cambios. 12 tests nuevos
(210/210). MEDIDO 2026-07-11: el feed de precios demo tiene high/low inflados $80-250/vela 1H →
NUNCA usar flag=1 para market data (confirma la regla de CLAUDE.md con datos).
**HALLAZGO P1 (arreglar ANTES de live):** `OKXClient._live_place_order` no fija `tgtCcy` — en
OKX spot un market BUY interpreta `sz` como QUOTE (USDT), no BASE (BTC): compraria ~64000x menos
de lo pedido. El cliente demo ya lo fija (`tgtCcy=base_ccy`); el fix en OKXClient necesita su
propio commit+test. La API key demo se crea DENTRO del modo demo trading de OKX (la real NO vale).

**PRUEBAS DEMO EN DEV (2026-07-13) — cuenta EEA/MiCA, hallazgos CRITICOS:**
- La cuenta de Matias es de la entidad europea: API en `https://my.okx.com` (keys EEA dan 60032
  contra www.okx.com). Nuevo `OKX_DEMO_DOMAIN` en settings/cliente. Feed de señales sigue global.
- **BTC-USDT y BTC-USD = sCode 51155 bloqueados por compliance (MiCA)** en su cuenta. El bot demo
  registrado como BTC-USDT NO puede operar: hace falta mapeo señal(BTC-USDT)→ejecucion(BTC-USDC
  o BTC-EUR). Fondos demo EEA: USDC/EUR/USD/XRP/ETH — CERO USDT.
- BTC-USDC permitido: BUY market OK (tgtCcy verificado contra API real). SELLs cancelados por el
  motor: book demo USDC casi muerto (top bid 59475 < banda minima de venta 51138 @59517).
  BTC-EUR funciona completo (sell filled + fee EUR). Precios demo divergen ~5% del real.
- 2 bugs del cliente arreglados con las pruebas: (a) errores code=1 ahora exponen sCode/sMsg;
  (b) fill fantasma — market aceptada (sCode=0) y luego `state=canceled` sin fill se reportaba
  como filled; ahora `_query_order` mira `state` y reporta rejected/qty real. Tests 215/215.
- Verificado contra API real: auth, balance, espejo, buy market, limit+cancel, sell market (EUR).
- **Mapeo señal→ejecucion IMPLEMENTADO** (decision Matias 2026-07-13: ejecutar en USDC — fees
  identicas a EUR pero spread real 0.02 vs 0.27 bps y misma unidad de cuenta que el backtest;
  conversion a EUR solo al retirar). `OKXDemoClient(exec_quote="USDC")`: ordenes/consultas *-USDT
  → *-USDC, balance USDC presentado como USDT; la estrategia y /status siguen en espacio USDT.
  Config del bot: `execution_quote: "USDC"` en okx_demo_setup.py, enrutado en live_cmds.py.
  Verificado E2E contra la API demo real: BUY "BTC-USDT" → fill real en BTC-USDC. Tests 219/219.

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
- Swing v1/v2 config exactas: ver "SWING ALLOCATOR — REFERENCIA" en docs/archive/session-archive.md.

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

## SIGUIENTE PASO (sesion 2026-07-12)

**Inmediato (retomado de 2026-07-11):**
1. `git push` de `7107631` (explain/EXPERIMENTS/audit) + commit y push del cliente OKX demo
   (`core/okx_demo_client.py`, `cli/live_cmds.py`, `tools/okx_demo_setup.py`, `config/settings.py`,
   `.env.example`, `tests/test_okx_demo_client.py`).
2. Deploy del bot demo en la VM: Matias crea la API key DEMO en OKX (dentro del modo demo trading)
   y añade `OKX_DEMO_API_KEY/SECRET_KEY/PASSPHRASE` al `.env` de la VM → `git pull` →
   `python tools/okx_demo_setup.py --enable` → `systemctl restart matibot` → verificar `/bots`
   (4o bot label `demo`) y su primera evaluacion 4H (orden INIT real en el engine demo de OKX).
   Ideal: cuenta demo solo con USDT (si ya tiene BTC, no hay INIT, rebalancea directo).
3. ~~Fix P1 `tgtCcy` en `OKXClient._live_place_order`~~ HECHO 2026-07-13 (mismo bloque que el
   cliente demo + 3 tests en `test_exchange.py`; suite 213/213).

**Marco general:** optimizacion de backtest del Swing = CERRADA. Hito = validacion forward:
cerrar F13 (smoke 24h), F15 (paridad 30d — racha reiniciada ~2026-07-11 por el incidente cron)
y F19 (degradacion). Live real planeado para SEPTIEMBRE 2026 (`start` live requiere confirmacion
explicita). El paper v5-vs-v6 empieza a dar señal desde ~2026-10-07.

---

## PENDIENTES ABIERTOS (todos cerrados/parqueados — NO reabrir sin evidencia nueva)

- **Max DD Swing (-52.73%):** frente CERRADO (sesion 15). Suelo estructural; nace en bull_peak y
  accumulation/COVID, NO en bear_onset. Todo lever probado agota CAGR o es inerte.
- **Q4 2025 ping-pong:** residual estructural, sin via viva. Descartados cooldown=7d, ADX gate,
  cap-bear_onset. Detalle en archive.
- **Pro Trend bugfixes candidatos** (P1, sin backtest aislado): fix MACD 4H key, fix VIX sizing cap.
- **`tgtCcy` en `OKXClient._live_place_order`:** ARREGLADO 2026-07-13 (market orders fijan
  `tgtCcy=base_ccy`, igual que el cliente demo; tests en `test_exchange.py`). Ya no bloquea live.
- **Funding Bybit 403 en la VM:** `funding_refresh.py` falla con HTTP 403 (IP de GCP bloqueada?).
  Sin urgencia hasta fase `accumulation` (~2026-10-07): sin ese cache, v6 degrada a v5 en silencio
  y PropSwing modela funding=0. Resolver antes de octubre.
- **Limpieza/refactor de codigo:** backlog en `docs/archive/refactor-backlog.md`. Difiere al cierre del paper
  (no romper determinismo/paridad). (El codigo muerto `execution/order_manager.py` +
  `position_tracker.py` ya se borro en `5ec7a97`, 2026-07-06.)
- **Descartado y NO reintentar:** latch del cap, regime_delta 0.15, VIX, MVRV, Pi Cycle, floor<0.20,
  global max_btc_pct cap, ATR intradia, halving_only, clock_aligned_cadence, fill_next_open.

---

## PUNTEROS A REFERENCIA (leer bajo demanda, NO precargar)

- `docs/handoff.md` — doc principal para continuar en otro PC (branch, setup, estado operativo,
  Prop/CFT, Swing v6, tests, siguientes pasos).
- `docs/ops/deploy-paper.md` — runbook y estado del despliegue paper en la VM.
- `docs/forward-test/contract.md` — reglas CONGELADAS del forward-test (inicio, variantes, fallo
  estrategia vs infra, playbook de incidentes). Citarlo por seccion en los reportes.
- `docs/forward-test/research-lab-plan.md` — roadmap del laboratorio de investigacion +
  monitorizacion (fases 0-6, tracking con checkboxes; fase 1-3 parcialmente HECHAS).
- `docs/swing/v6-plan.md` — plan v6 (phase router + funding overlay; criterios de promocion Fase 4).
- `docs/swing/plan.md` — diseño del Swing. `docs/swing/audits.md` — auditorias v4/v5 + plan de
  mejora F1-F19 (consolidado de los antiguos AUDITORIA_SWING_V4/V5 y PLAN_MEJORA_AUDITORIA).
- `docs/prop/hyrotrader-plan.md` — estrategia prop firm (Bybit/CFT/Hyro). Estado: motor `funding_extreme` da
  edge standalone real (PF 1.44, DD 13%) pero RECHAZADO como prop (gate two-step ~27% pass / 37%
  breach vs >=60%/<=20%). Router CFT-only (`entry_halving_phases=bear_onset,accumulation`) es el mejor
  candidato pero requiere validar reglas reales CFT/Match/MT5 — sin confirmacion escrita, NO comprar.
- `docs/archive/session-archive.md` — logs sesiones 12-18, auditorias, resultados backtest, referencia por modulo,
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
- Ejecucion: `core/exchange.py` (OKXClient real/paper local), `core/okx_demo_client.py` (hibrido
  demo OKX: data real + ordenes demo). Registro de experimentos: `EXPERIMENTS.md` (raiz).
- Umbrales y config detallada de cada modulo: docs/archive/session-archive.md.
