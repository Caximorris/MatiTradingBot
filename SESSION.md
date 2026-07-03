# SESSION.md — Estado del proyecto (HOT — se carga en cada sesion via @SESSION.md)

Complemento de CLAUDE.md. **Este archivo es deliberadamente corto** para no gastar tokens en
cada arranque. El detalle historico completo (logs de sesion, tablas de backtests, referencia de
cada modulo) vive en **`SESSION_ARCHIVE.md`** — leelo SOLO cuando lo necesites, no por defecto.

**Ultima actualizacion: 2026-07-02 (sesion 16 — Swing v5 post-audit congelado)**

Punteros a referencia (leer bajo demanda, NO precargar):
- `SESSION_ARCHIVE.md` — logs sesiones 12/13, auditoria 2026-06-30, resultados backtest, referencia
  detallada de Pro Trend v12/v13, macro/market/funding context, indicadores, bugs resueltos.
- `backtests/STRATEGY_VERSIONS.md` — historial de versiones de estrategia.
- `SWING_PLAN.md` — diseno y criterios go/no-go del Swing Allocator.
- `AUDITORIA_SWING_V4.md` — auditoria cuantitativa critica (2026-07-02): hallazgos B1-B5/C1-C9,
  sensibilidad calendario halving, ablations, tabla por anios. `PLAN_MEJORA_AUDITORIA.md` — plan
  paso a paso (F1-F19) para resolverlos (COMPLETADO salvo cierres que requieren paper: F13/F15/F19).
  `AUDITORIA_SWING_V5_POST_IMPLEMENTACION.md` — auditoria post-implementacion del freeze v5.
  Scripts en `tools/` (sens_phases, bootstrap_equity, stress_usdt_depeg, swing_benchmarks,
  swing_parity_check, degradation_report, swing_v5_freeze_report).
- Journals: NO hacer `Read` del JSON crudo (pueden ser >10 MB). Usar
  `python tools/journal_summary.py <ruta>` o `/journal-summary`.
- `HYROTRADER_PLAN.md` — estrategia prop firm (HyroTrader/Bybit). Estado final 2026-07-03:
  P0-P4 COMPLETADOS y **checkpoint FASE 7 disparado — NO comprar challenge**. Mejor candidato
  (prop_swing breakout + risk 1%): P(pasar) 11.8% << 60% go/no-go; EV negativo. Queda listo:
  `core/prop_rules.py` (simulador reglas prop), `strategies/prop_swing.py` (entry_mode
  pullback|breakout), `tools/prop_challenge_sim.py`. Swing v5 por el simulador = breach 100%
  (baseline). Retomable solo con un motor nuevo que de P(pasar)>=60% en el simulador.

---

## ESTADO ACTUAL

**DEFAULT VIGENTE: Swing Allocator v5 post-audit (2026-07-02, sesion 16) — CONGELADO.**
v5 = v4 estructural + `daily_on_closed_only=True` (F8, unico delta de comportamiento; el resto
del plan F1-F19 son motor/metricas/operativa live). Anclas v5 (dataset canonico 102931):
- 2015-26 realistic: $9.137M | CAGR +85.84% | Max DD -52.73% | 70 rebalanceos | btc_vs_bnh 0.8171
- 2018-26 realistic: $219.8k | CAGR +47.14% | Max DD -53.72% | 53 rebalanceos | btc_vs_bnh 0.8432
- 2015-26 conservative: $8.897M | CAGR +85.40% | Max DD -52.88% | 70 | btc_vs_bnh 0.7961
Coste del fix anti-lookahead vs v4: -0.27pp CAGR / -0.02pp DD — adoptado por higiene, no resultado.
Rollback exacto a v4 congelado: `--config '{"daily_on_closed_only": false}'`. Tests 88/88 verde.
NOTA (2026-07-03): estas anclas son RUTA-TOOL (`tools/swing_v5_freeze_report.py`). El CLI
(`main.py backtest`) da $9.164M / +85.9% en 2015-26 realistic — NO es regresion: difiere la
contabilidad del warmup (CLI analiza 96930 velas, tool 96907; 23 velas en el tramo 2014 con
huecos), desplaza el INIT y desvia la valoracion USD +0.29%. DD/ratio/rebalanceos identicos.
Smoke por CLI debe comparar contra $9.164M; smoke por tool contra $9.137M exacto.
Auditoria post-implementacion: `AUDITORIA_SWING_V5_POST_IMPLEMENTACION.md`. CONGELADO en tag
`swing-v5-frozen` @ 4c955fb (2026-07-02).

**FOCO UNICO: Swing Allocator.** Pro Trend queda PAUSADO INDEFINIDAMENTE (decision 2026-07-01,
sesion 14). No se continua ni paper trading ni optimizacion por ahora. El codigo queda como esta
(v13, congelado y reversible). Retomable en el futuro, pero fuera del roadmap activo.

**Pro Trend v13** (CONGELADO — no se continua). Framework de validacion estaba COMPLETADO.
- 2018-2026 realistic: +521.84% / CAGR +25.7% (partial_exit=150%) vs B&H +550% / +26.4%.
- 2015-2026 realistic: +5812% / CAGR +44.9% — 3 ciclos bull validados.
- Ventaja real: riesgo, no retorno. 35% tiempo en mercado, evita crashes -70%.

**Swing Allocator v4** (2026-07-01, sesion 14 — SUPERSEDIDO por v5, ver arriba; v4 sigue siendo
la referencia estructural congelada en tag `swing-v4-frozen`). Paso go/no-go completo.
- Cambio v3->v4: `min_btc_pct` 0.30->0.20 y `delta_bear_onset` -0.20->-0.30. Resto de v3 intacto
  (regime_off_on_bear_onset=True, bull_peak_ema50_cap=0.85). Mejora AMBAS anclas a la vez.
- Mecanismo estructural: el floor 0.30 clampeaba y bloqueaba el estado de bear profundo (las senales
  nunca calculan <0.20). Bajarlo desbloquea "mas USDT en bear -> recompra mas barata" = la tesis central.
- 2015-2026 realistic: CAGR +86.2% / Max DD -52.71% (v3: 82.4% / -53.64%) → +3.8pp / -0.9pp.
- 2015-2026 conservative: +85.7% / -52.86%. 2018-2026 realistic: +47.6% / -53.42% (+4.6pp CAGR).
- WF 4/4 TEST positivo (CAGR 21.5/41.5/20.8/82.4%, PF>1.8). ETH inerte (cambios BTC-especificos) ✅.
- Rollback: `--config '{"min_btc_pct": 0.30, "delta_bear_onset": -0.20}'` vuelve a v3.
- DD residual reordenado: max ahora 2019->COVID (-53%) y flash-crash mayo-2021 (-50%). ~50-52% es el
  suelo estructural de long-only 100% en mercado — NO perseguir (rompe tesis o cuesta CAGR, ver latch).

**HECHO (sesion 15, 2026-07-02):**
- **Smoke-verify v4 OK**: `backtest --strategy swing 2015-2026 realistic` reproduce CAGR +86.2% /
  Max DD -52.71% / 68 rebalanceos / 96930 velas analizadas. Las 5 metricas nuevas se muestran
  (Median trade +602 legacy, Calmar 1.63, DD duracion 260d, Sharpe 1.38, Sortino 1.57).
- **Cache 102931 ADOPTADO como canonico** (decision 2026-07-02): BTC-USDT_1H 2014-04-25 → 2026-01-01,
  continuo, cero huecos >24h. Reemplaza al viejo de 96906. v4 validado sobre el (WF 4/4, ETH inerte,
  smoke OK). El PF legacy 4.43 era artefacto de pairing; tras F1 el PF ACB del smoke es 88.38,
  confirmando que PF/WR/expectancy siguen siendo metricas contables de rebalanceos, NO anclas de
  decision. Anclas siguen siendo CAGR/DD/Calmar y BTC vs B&H.

**HECHO (sesion 15 bis, 2026-07-02): v4 commiteado y CONGELADO** (tag `swing-v4-frozen` @ 06395ff).
Auditoria completa en `AUDITORIA_SWING_V4.md`; plan de ejecucion en `PLAN_MEJORA_AUDITORIA.md`
(en curso, ver checkboxes alli).

**HECHO (sesion 16, 2026-07-02): F1-F4 parciales cerrados.**
- F1: `_compute_trade_pnl_acb` con coste medio ponderado, fees prorrateados y selector interno
  `trade_pnl_method="acb"|"legacy_fifo"`. Tests: `python -m pytest tests/test_backtest_pnl.py -q` = 6/6.
- F2: `underwater_days` real (peak->recovery) junto a `max_dd_duration_days` (peak->trough).
- Smoke v4 post-F1/F2: final $9.307M, CAGR +86.2%, Max DD -52.71%, 96930 velas, underwater 922d.
  Equity sin cambios; solo cambian metricas por rebalanceo.
- F3: README y CLI dejan de presentar PF del Swing como veredicto.
- F4: umbrales de fase de halving parametrizados (`phase_post_end/phase_peak_end/phase_onset_end`)
  con defaults 180/540/900; smoke default reproduce anclas.
- F5: matriz calendario completa sobre v4 congelado. El signo del edge sobrevive en todas las
  variantes, pero el reloj sigue fragil: shift -60d baja CAGR a +72.86%; shift +60d sube DD a -66.08%.
- F6: `halving_only` extra RECHAZADO como simplificacion. 2018 realistic: +41.66% CAGR / -50.91%
  DD / `btc_vs_bnh=0.6410` vs v4 +47.59% / -53.42% / 0.8641. Conservative 2015: +73.56% /
  -50.91% / 0.4004 vs v4 +85.65% / -52.86% / 0.8082. Mantener `use_regime=True`.
- F7: bootstrap mensual v4 congelado x1000: MaxDD p50 -53.01%, p95 -68.31%, p99 -74.34%;
  sizing futuro debe usar p95/p99, no el -52.7% historico.
- F8: `daily_on_closed_only=True` ADOPTADO por higiene anti-lookahead. Impacto aislado: CAGR
  +85.84% vs +86.11%, DD -52.73% vs -52.71%. Rollback: `--config '{"daily_on_closed_only": false}'`.
- F9: `clock_aligned_cadence=True` MEDIDO y NO adoptado. Empeora CAGR a +84.62% y no reduce
  sensibilidad al offset 2015-01-02.
- F10: `fill_next_open` medido y NO adoptado como default: impacto despreciable (+86.08% vs +86.11%,
  DD igual). Se mantiene para mediciones en `BacktestClient(fill_next_open=True)`.
- F11: B&H ahora incluye coste de compra; `lookback_hours` documenta que EMA200D es truncada.
- F12: `OKXClient.get_ohlcv` pagina hasta `limit` y devuelve `timestamp` ms `int64`, igual que
  `BacktestClient`. Smoke OKX real: 6000 filas 1H / dtype int64.
- F13: ruta `start` ya instancia Swing y pasa `RiskManager`; Swing bloquea compras si
  `check_daily_loss()` dispara, pero permite ventas defensivas. NO se ejecuto `start` (requiere OK
  explicito y 24h para cerrar operativo).
- F14: controles minimos Swing paper/live: rechazo de tick anomalo (`max_price_jump_pct=0.25`),
  OHLCV insuficiente bloquea decisiones live, `main.py stop` es kill switch, rebalanceos live/paper
  se persisten en `data/runtime/swing_rebalances.jsonl`.
- F16: stress USDT depeg current default. Depeg -10% en 2018-06: CAGR +84.37%, final $8.37M.
  Depeg -10% en 2022-06: CAGR +84.30%, final $8.34M. Riesgo aceptable en backtest, pero capital
  estable/custodia siguen siendo riesgo real.
- F17 sizing formal: dimensionar con MaxDD p95/p99 bootstrap (-68%/-74%), no con -52.7% historico.
  Conservador 10-20% del patrimonio cripto; moderado 30-50%; agresivo solo si sustituye el sleeve BTC
  completo y se acepta DD tipo -75%. Sin apalancamiento; limitar custodia concentrada en un exchange.
- F15 parcial: `tools/swing_parity_check.py` compara target live/backtest con las mismas 6000 velas.
  Check puntual OK 2026-07-02 12:00 UTC: ambos target 0.2000, `regime_bear;halving_bear_onset`.
  Cierre real sigue siendo 30 dias de paper sin divergencias.
- F18 parcial: `tools/swing_benchmarks.py` implementa benchmarks Swing. 2015-2026 realistic current:
  Swing $9.14M / CAGR +85.84% / DD -52.73%; 60/40 mensual $540k / +43.71% / -65.01%;
  EMA200D long/flat $1.47M / +57.36% / -74.93%; DCA semanal $539k / +43.69% / -79.06%.
  Falta integrar estos benchmarks en `main.py baselines`/README.
- F19 parcial: `tools/degradation_report.py` lee `data/runtime/swing_rebalances.jsonl` y alerta por
  frecuencia >2x backtest o gap target/after >2pp. Sin datos live aun (`no_data` esperado).

**Descartado sesion 14 (no reintentar):** latch del cap (`bull_peak_cap_latch`), regime_delta 0.15,
VIX, MVRV (wash), Pi Cycle (inerte), floor <0.20 (inerte, senales nunca bajan de 0.20).

**Descartado sesion 15 (no reintentar): cap-target con `bear_onset` activo.** Ataca la fase
equivocada. Evidencia empirica (journal v4 2015-26, target medio por fase temporal del halving):
post_halving 0.89 | **bull_peak 0.91** | **bear_onset 0.30** | accumulation 0.63. El Max DD nace en
bull_peak (techos 2013/17/21-abr/25 + flash-crash mayo-21) y accumulation (COVID @0.63), NO en
bear_onset — que dispara a 540d, cuando el crash del techo ya paso y el delta -0.30 ya bajo el target
a 0.30. Un cap sobre bear_onset ataria en 1 de 8 rebalanceos = overfit de 1 evento.

**FRENTE DE MAX DD CERRADO (sesion 15).** El -52.71% (v4) es el suelo estructural de long-only ~100%
en mercado. Todo lever probado o agota CAGR o es inerte: global max_btc_pct cap (mata CAGR), latch
(-4.6pp CAGR), floor<0.20 (inerte), bear_onset cap (inerte). Unico lever no explorado = de-risk
intradia por spike ATR para crash tipo-COVID; DESCARTADO por diseno (rediseno mayor, overfit sobre 1
evento, probable coste de CAGR en whipsaws). No perseguir mas DD. Proximo hito Swing = validacion
forward / paper trading, no mas optimizacion de backtest.

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
  al punto de inicio — ver sesion 13). Fijar siempre inicio 2015.
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
- v4 congelado en tag `swing-v4-frozen` (commit 06395ff).

### 4. Determinismo de datos
- Backtests deterministas via cache OHLCV (`data/cache/`). Runs con rango cacheado = velas identicas.
- Resultado SENSIBLE al punto de inicio (dataset canonico: 102931 velas, adoptado 2026-07-02; viejo 96906). No mezclar caches entre maquinas.
- Backtests CONTINUOS — nunca reiniciar balance en frontera de año/mes.

---

## SIGUIENTE PASO — Swing Allocator (foco unico)

Pro Trend pausado. **Optimizacion de backtest del Swing = CERRADA** (v5 post-audit default, frente
de Max DD agotado, ver arriba). El proximo hito NO es mas backtest: es **validacion forward /
paper trading** del Swing v5 (cierra F13 24h + F15 paridad 30d + F19 datos de degradacion).
`start` en vivo requiere confirmacion explicita.

**HECHO (sesion 16 bis, 2026-07-02): fixes de la ruta live/paper (post-freeze, no tocan senales).**
Al preparar el arranque del paper se detecto que la ruta live NO funcionaba: el scheduler de
`start` re-instancia la estrategia en cada tick y el Swing no persistia estado → tras el INIT
nunca volvia a rebalancear; ademas el balance paper vivia en memoria (reinicio = portfolio a $10k)
y `bot add` no aceptaba swing. Fixes aplicados:
- Estado live del Swing persistido en BotState fila ("swing_allocator", symbol, is_active=False),
  mismo patron que Pro Trend: `initialized`, `last_rebalance`, `last_eval_block`.
- Cadencia live = UNA evaluacion por bloque 4H UTC (persistida; robusta a restarts y a cualquier
  tick). Si los datos de mercado fallan, el bloque NO se consume (reintento al siguiente tick).
  Backtest mantiene su cadencia exacta `_bar_count % 4` (sin cambio de comportamiento).
- Balance paper persistido en `data/runtime/paper_state.json` (opt-in via `_make_client`; los
  tests no tocan disco). Limit orders pendientes NO sobreviven restart (el Swing solo usa market).
- `bot add swing BTC-USDT` funciona; filtro tick-anomalo (F14) ahora SOLO live/paper (resuelve M2
  de la auditoria v5). Ancla 2015-26 realistic re-verificada identica. Tests 96/96.
Paper listo para arrancar: `python main.py bot enable swing_allocator_btc_usdt BTC-USDT` +
`python main.py start` (requiere OK explicito y proceso vivo; reinicios ya no pierden estado).

**HECHO (sesion 16 ter, 2026-07-02): infra cloud para el paper — plan aprobado por Matias.**
El paper correra en VM gratuita (Oracle Free / GCP e2-micro) con control remoto por Telegram.
**Runbook completo y ESTADO DEL DESPLIEGUE en `DEPLOY_PAPER.md`** (ese doc es el punto de
reanudacion si esto se pausa). Piezas: `tools/telegram_remote.py` (/status /report /pause
/resume + alertas de rebalanceo, long-polling sin puertos), `tools/tg_send.py`,
`deploy/install_vm.sh` + units systemd (Restart=always) + `daily_checks.sh` (cron 12:10 UTC:
paridad F15 + degradacion F19, alerta si PARITY_FAIL). Los 11 tools con ROOT hardcodeado
Windows ahora son portables a Linux. `.env` en VM: OKX_SANDBOX=false (datos reales; el demo
romperia paridad) + TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID. Pendiente de Matias: cuenta cloud
y bot de @BotFather. data/runtime/ y trading.db gitignored.

**HECHO (sesion 14):**
- Auditoria del cap `bull_peak_ema50_cap_*`: 24 disparos en 2015-26, TODOS SELL 100%->85%, en los 3
  techos (2017:9, 2021:5, 2024-25:10). Estructural, NO overfit a un evento. PERO casi todos en PARES
  (btc_pct_before=0.9997 siempre) => es ping-pong sell-85%/rebuy-100% en el techo. Feb y Ago 2025 =
  3 ventas cada uno. El cap solo aporta 1.6pp de Max DD (v2 -55.23 -> v3 -53.64).
- **Latch del cap PROBADO Y DESCARTADO.** `bull_peak_cap_latch` mantiene el cap hasta cambio de fase.
  Mecanismo OK (24->3 disparos) pero PEOR: dispara early y handcuffea a 85% todo el rally
  (2017 $827->$19k). 2015 realistic CAGR 81.39->76.8% (-4.6pp), DD ni mejora (-53.64->-54.02).
  Conservative 80.93->76.5%. El rebuy-a-100% de v3 era CORRECTO. Q4 2025 mejora aislado = overfit.

**Candidatas para Max DD: TODAS descartadas (frente cerrado sesion 15).** Ver bloque "FRENTE DE
MAX DD CERRADO" arriba. cap-target-on-bear_onset (inerte, fase equivocada), latch, floor<0.20,
global caps, ATR intradia — todas agotan CAGR o son inertes. NO reabrir sin evidencia nueva.

Regla dura (si algun dia se reabre): candidato se compara por CAGR y Max DD (anclas), PF como rango,
inicio 2015 fijo, AISLADO vs baseline v4.

---

## PENDIENTES ABIERTOS

- **Q4 2025 (Swing):** ping-pong estructural residual. Sin via viva (cap-bear_onset descartado sesion 15).
  Descartados: cooldown=7d, ADX gate. Detalle en SESSION_ARCHIVE.md ("Q4 2025 mitigacion"). NO reabrir.
- **Max DD Swing (-52.71% v4):** FRENTE CERRADO (sesion 15). Es el suelo estructural de long-only.
  Nace en bull_peak (target medio 0.91) y accumulation/COVID (0.63), NO en bear_onset. Ver bloque
  "FRENTE DE MAX DD CERRADO". No perseguir.
- **Pro Trend bugfixes candidatos** (P1, sin backtest aislado aun): fix MACD 4H key,
  fix VIX sizing cap (ya en codigo, pendiente validar). Ver auditoria en SESSION_ARCHIVE.md.

---

## DONDE ESTA CADA COSA (referencia rapida, sin abrir el archivo)

- Estrategias: `strategies/pro_trend.py`, `strategies/swing_allocator.py`, `strategies/adaptive_trend.py`,
  `strategies/scalp_momentum.py`. Indicadores: `strategies/indicators.py` (UNICO activo).
- Contexto externo: `strategies/macro_context.py` (MVRV+halving), `strategies/market_context.py`
  (DXY/NDX/VIX), `strategies/funding_context.py`.
- Backtest: `core/backtest.py`. Cache: `data/ohlcv_cache.py`. Journals: `reporting/trade_journal.py`,
  `reporting/swing_journal.py`.
- Umbrales y config detallada de cada modulo: SESSION_ARCHIVE.md.
