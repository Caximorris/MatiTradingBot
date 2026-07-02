# SESSION.md — Estado del proyecto (HOT — se carga en cada sesion via @SESSION.md)

Complemento de CLAUDE.md. **Este archivo es deliberadamente corto** para no gastar tokens en
cada arranque. El detalle historico completo (logs de sesion, tablas de backtests, referencia de
cada modulo) vive en **`SESSION_ARCHIVE.md`** — leelo SOLO cuando lo necesites, no por defecto.

**Ultima actualizacion: 2026-07-02 (sesion 15)**

Punteros a referencia (leer bajo demanda, NO precargar):
- `SESSION_ARCHIVE.md` — logs sesiones 12/13, auditoria 2026-06-30, resultados backtest, referencia
  detallada de Pro Trend v12/v13, macro/market/funding context, indicadores, bugs resueltos.
- `backtests/STRATEGY_VERSIONS.md` — historial de versiones de estrategia.
- `SWING_PLAN.md` — diseno y criterios go/no-go del Swing Allocator.
- Journals: NO hacer `Read` del JSON crudo (pueden ser >10 MB). Usar
  `python tools/journal_summary.py <ruta>` o `/journal-summary`.

---

## ESTADO ACTUAL

**FOCO UNICO: Swing Allocator.** Pro Trend queda PAUSADO INDEFINIDAMENTE (decision 2026-07-01,
sesion 14). No se continua ni paper trading ni optimizacion por ahora. El codigo queda como esta
(v13, congelado y reversible). Retomable en el futuro, pero fuera del roadmap activo.

**Pro Trend v13** (CONGELADO — no se continua). Framework de validacion estaba COMPLETADO.
- 2018-2026 realistic: +521.84% / CAGR +25.7% (partial_exit=150%) vs B&H +550% / +26.4%.
- 2015-2026 realistic: +5812% / CAGR +44.9% — 3 ciclos bull validados.
- Ventaja real: riesgo, no retorno. 35% tiempo en mercado, evita crashes -70%.

**Swing Allocator v4 ADOPTADO como default** (2026-07-01, sesion 14). Pasa go/no-go completo.
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
  Max DD -52.71% / PF 4.43 / 68 trades / 96930 velas analizadas. Las 5 metricas nuevas se muestran
  (Median trade +602, Calmar 1.63, DD duracion 260d, Sharpe 1.38, Sortino 1.57).
- **Cache 102931 ADOPTADO como canonico** (decision 2026-07-02): BTC-USDT_1H 2014-04-25 → 2026-01-01,
  continuo, cero huecos >24h. Reemplaza al viejo de 96906. v4 validado sobre el (WF 4/4, ETH inerte,
  smoke OK). El PF 4.43 es sano pese a mas relleno Bitstamp que el 97105 sospechoso, porque el 102931
  es relleno COMPLETO/continuo, no parcial. Anclas siguen siendo CAGR/DD, no PF.

**PENDIENTE (sesion 15):**
- **Commitear v4 + metricas** (sin commitear aun): 5 archivos. Sugerido 2 commits (metricas backtest /
  swing v4 default) y push a origin/main.

**Descartado sesion 14 (no reintentar):** latch del cap (`bull_peak_cap_latch`), regime_delta 0.15,
VIX, MVRV (wash), Pi Cycle (inerte), floor <0.20 (inerte, senales nunca bajan de 0.20).

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

### 4. Determinismo de datos
- Backtests deterministas via cache OHLCV (`data/cache/`). Runs con rango cacheado = velas identicas.
- Resultado SENSIBLE al punto de inicio (dataset canonico: 102931 velas, adoptado 2026-07-02; viejo 96906). No mezclar caches entre maquinas.
- Backtests CONTINUOS — nunca reiniciar balance en frontera de año/mes.

---

## SIGUIENTE PASO — Swing Allocator (foco unico)

Pro Trend pausado; toda la energia va a mejorar Swing v3.

**HECHO (sesion 14):**
- Auditoria del cap `bull_peak_ema50_cap_*`: 24 disparos en 2015-26, TODOS SELL 100%->85%, en los 3
  techos (2017:9, 2021:5, 2024-25:10). Estructural, NO overfit a un evento. PERO casi todos en PARES
  (btc_pct_before=0.9997 siempre) => es ping-pong sell-85%/rebuy-100% en el techo. Feb y Ago 2025 =
  3 ventas cada uno. El cap solo aporta 1.6pp de Max DD (v2 -55.23 -> v3 -53.64).
- **Latch del cap PROBADO Y DESCARTADO.** `bull_peak_cap_latch` mantiene el cap hasta cambio de fase.
  Mecanismo OK (24->3 disparos) pero PEOR: dispara early y handcuffea a 85% todo el rally
  (2017 $827->$19k). 2015 realistic CAGR 81.39->76.8% (-4.6pp), DD ni mejora (-53.64->-54.02).
  Conservative 80.93->76.5%. El rebuy-a-100% de v3 era CORRECTO. Q4 2025 mejora aislado = overfit.

**Candidatas vivas para Max DD (cada una AISLADA vs baseline v3, ventana 2015 principal):**
- Cap-target cuando `bear_onset` activo (distinto de bull_peak; ataca la transicion de techo).
- NO extender el cap EMA50D a `post_halving`: la auditoria sugiere que anadiria mas whipsaw.
- Combinar y re-validar WF 4/4 + ETH solo si una candidata aporta aislada.

Regla dura: candidato nuevo se compara por CAGR y Max DD (anclas), PF como rango, inicio 2015 fijo.
`start` en vivo sigue requiriendo confirmacion — pero Swing NO va a paper aun, primero backtests.

---

## PENDIENTES ABIERTOS

- **Q4 2025 (Swing):** ping-pong estructural residual. Via viva: cap-target con `bear_onset` activo.
  Descartados: cooldown=7d, ADX gate. Detalle en SESSION_ARCHIVE.md ("Q4 2025 mitigacion").
- **Max DD Swing (-55%):** viene de estar 90-100% BTC en TECHOS de ciclo, no de los bears.
  Caps globales de `max_btc_pct` descartados (destruyen CAGR). v3 ataca el techo quirurgicamente.
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
