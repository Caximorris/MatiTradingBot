# PLAN DE MEJORA — auditoria Swing v4 (2026-07-02)

Fuente: `AUDITORIA_SWING_V4.md`. Cada paso tiene objetivo, archivos, como validar y criterio de
cierre. Orden pensado para resolver primero lo que cambia decisiones (metricas y validez) y
despues lo operativo. Marcar `[x]` al cerrar cada paso y anotar resultado.

**Reglas transversales del plan:**
- La ventana 2015-2026 queda CERRADA para optimizacion. Los pasos de este plan solo la usan para
  MEDIR (sensibilidad/robustez), nunca para elegir parametros nuevos.
- Todo cambio de codigo reversible por config o por commit atomico propio.
- Las anclas siguen siendo CAGR y Max DD. PF no se cita hasta cerrar F1.

---

## FASE 0 — Congelacion (hacer YA, antes de tocar nada)

### 0.1 Commitear v4 pendiente y etiquetar version congelada
- **Objetivo:** que exista un punto de rollback exacto de "v4 auditado".
- **Acciones:** los 2 commits pendientes de sesion 15 (metricas backtest / swing v4 default),
  push a origin/main, y tag `swing-v4-frozen` (git tag, requiere OK explicito de git).
- **Cierre:** `git tag` muestra el tag; SESSION.md apunta al hash.

### 0.2 Declarar el protocolo out-of-sample en SESSION.md
- **Objetivo:** matar el data snooping de proceso (hallazgo B5).
- **Acciones:** anadir regla invariante #5: "Ningun cambio de estrategia se adopta por mejorar
  2015-2026. Esa ventana solo compara robustez. La evidencia para cambios futuros = datos
  posteriores a 2026-01-01 (forward/paper) o justificacion estructural pura."
- **Cierre:** regla escrita en SESSION.md, seccion reglas invariantes.

---

## FASE 1 — Metricas honestas (cambian como leemos TODO backtest futuro)

### F1. Arreglar P&L por trade del allocator (hallazgo B3)
- **Objetivo:** que PF/win-rate/expectancy/median signifiquen algo para rebalanceos parciales.
- **Archivos:** `core/backtest.py:616-639` (`_compute_trade_pnl`).
- **Diseno:** pairing por cantidades con coste medio (average cost basis):
  - Mantener por simbolo: `qty_abierta` y `coste_medio`.
  - BUY: recalcula coste medio ponderado.
  - SELL: PnL = (precio_venta - coste_medio) * qty_vendida - fees prorrateados; reduce qty_abierta.
  - Cada SELL = un "trade cerrado" con su PnL real.
- **Compatibilidad:** anadir como metodo nuevo (`_compute_trade_pnl_acb`) usado por defecto,
  dejar el viejo accesible tras flag para reproducir numeros historicos si hace falta comparar.
- **Validar:** para una estrategia todo-in/todo-out (Pro Trend) los numeros deben coincidir ~con
  el metodo viejo; para el Swing, PF debe volverse estable entre variantes (hoy: 2.3→117.8).
- **Cierre:** re-run smoke v4 → nuevas metricas documentadas en SESSION.md como "anclas v2 de
  metricas por-trade" (CAGR/DD no deben moverse NADA — si se mueven, bug).

### F2. Underwater duration real (hallazgo C4)
- **Objetivo:** reportar el tiempo bajo el agua (peak→recovery), no solo peak→trough.
- **Archivos:** `core/backtest.py` — nueva metrica `underwater_days` junto a la actual;
  `summary_rows()` muestra ambas.
- **Cierre:** smoke v4 reporta ambas; esperar ~900-1000d para el peor periodo (2021-2024).

### F3. Dejar de citar PF del Swing en docs
- **Objetivo:** que README/SESSION no anclen decisiones a una metrica rota.
- **Archivos:** `README.md`, `SESSION.md` — nota "PF del Swing = artefacto del pairing hasta F1".
- **Cierre:** grep de "PF 4.43" en docs devuelve solo menciones historicas anotadas.

---

## FASE 2 — Acotar el overfitting del calendario (hallazgos B1, B2)

### F4. Hacer configurables los umbrales de fase de halving
- **Objetivo:** que el parametro mas importante del sistema entre al mismo protocolo que el resto.
- **Archivos:** `strategies/macro_context.py:162-196` — extraer 180/540/900 a parametros
  (`PHASE_POST_END=180, PHASE_PEAK_END=540, PHASE_ONSET_END=900`) con override desde
  `SwingAllocatorConfig` (pasandolos por `get_macro_signal` o setter de modulo).
- **Riesgo:** Pro Trend tambien consume `halving_phase` — los defaults NO cambian, solo se
  parametriza. Verificar que Pro Trend con defaults da resultados identicos (esta congelado).
- **Cierre:** backtest v4 con defaults reproduce exactamente CAGR +86.2% / DD -52.71%.

### F5. Matriz de sensibilidad completa del calendario (medir, NO elegir)
- **Objetivo:** documentar la fragilidad real del edge. Ya medido: 480d (-10.7pp CAGR),
  600d (DD -66.1%).
- **Runs pendientes (2015-2026 realistic, aislados):**
  - `PHASE_POST_END`: 120, 240 (default 180)
  - `PHASE_ONSET_END`: 800, 1000 (default 900)
  - Reloj global desplazado: todas las fronteras +30d; todas -30d; +60d; -60d
- **Herramienta:** generalizar el script de la auditoria (esta en scratchpad `sens_halving.py`)
  → `tools/sens_phases.py` versionado.
- **Regla dura:** los resultados se DOCUMENTAN en AUDITORIA (tabla), no se usa el mejor para
  cambiar defaults (seria una consulta mas al mismo dataset).
- **Cierre:** tabla completa en AUDITORIA_SWING_V4.md + parrafo de conclusion: ¿el signo del edge
  (batir B&H en CAGR con menos DD) sobrevive en TODAS las variantes? Si no, anotar cuales caen.

### F6. Ablation halving-only en ventanas/costes restantes
- **Objetivo:** decidir si `use_regime` gana su lugar (aporta +12.5pp CAGR en 2015-26 pero la
  atribucion por tramos del regime es destructiva; halving-only: 73.7%/-50.9% con 13 trades).
- **Runs:** halving-only vs v4 en 2018-2026 realistic y en 2015-2026 conservative.
- **Decision posible:** si regime no aporta fuera del tramo Bitstamp, considerar "v5 = v4 sin
  regime" como candidata SIMPLIFICADORA (menos parametros, menos trades, menos DD) — esto es
  reduccion de complejidad, permitida aunque la ventana este cerrada, si NO empeora las anclas.
- **Cierre:** decision documentada en SESSION.md (mantener regime / retirar regime).

### F7. Bootstrap por bloques de la equity v4
- **Objetivo:** intervalo de confianza del Max DD (esperar -70/-80% en p95) y del CAGR.
- **Herramienta:** `tools/bootstrap_equity.py` — bloques mensuales de retornos de la equity v4,
  resampleo con reemplazo x1000, distribucion de CAGR/MaxDD.
- **Cierre:** percentiles documentados en AUDITORIA; el sizing de FASE 5 se dimensiona con p95,
  no con el historico.

---

## FASE 3 — Limpieza del motor y de la estrategia (hallazgos C1, C2, C6, C7, C9)

### F8. Indicadores diarios solo con dias cerrados (C2)
- **Objetivo:** cumplir la regla invariante #1 en el propio Swing.
- **Archivos:** `strategies/swing_allocator.py:474-508` — calcular ema50d/ema200d/rsi/adx/pi_cycle
  sobre `closed_daily` (como ya hace `ema50d_closed`), tras flag
  `daily_on_closed_only: bool = True` (rollback: False).
- **Validar:** backtest aislado vs baseline v4. Si cambia mucho las anclas, investigar por que
  antes de adoptar (un cambio grande aqui = la senal dependia del dia parcial = mala senal).
- **Cierre:** resultado documentado; flag default decidido por robustez, no por CAGR.

### F9. Cadencia alineada a reloj (C6)
- **Objetivo:** eliminar la dependencia del offset de warmup (sensibilidad al punto de inicio).
- **Archivos:** `swing_allocator.py:179-181` — evaluar cuando `current_time().hour % 4 == 0`
  en vez de `_bar_count % 4`, tras flag `clock_aligned_cadence: bool = True`.
- **Validar:** backtest aislado; ademas re-run con from 2015-01-02 (offset +1 dia) → el resultado
  deberia moverse MENOS que antes.
- **Cierre:** sensibilidad al punto de inicio medida antes/despues y documentada.

### F10. Fill en la vela siguiente (C1) — solo medir
- **Objetivo:** cuantificar el optimismo del fill al close de la vela de decision.
- **Accion:** modo opcional `fill_next_open` en `BacktestClient._fill_market` (fila en la barra
  siguiente al open ± slippage). Correr v4 con el una vez.
- **Regla:** si el impacto es <1pp CAGR (esperado a escala 540d), documentar y NO cambiar el
  default (evita romper comparabilidad). Si es mayor, adoptar y re-anclar.
- **Cierre:** delta documentado en AUDITORIA.

### F11. Menores: B&H con coste (C9) + doc de EMA truncada (C7)
- `backtest.py:476-478`: aplicar fee+slip de una compra al benchmark B&H.
- `swing_allocator.py:107`: comentario documentando que la "EMA200D" es truncada a la ventana
  `lookback_hours` y que cambiar ese valor cambia las senales.
- **Cierre:** ambos triviales, un commit.

---

## FASE 4 — Ruta paper/live real (hallazgo B4). Prerequisito para el hito de SESSION.md

### F12. `OKXClient.get_ohlcv` con paginacion y formato identico al backtest
- **Objetivo:** que `limit=6000` funcione de verdad y con el mismo schema.
- **Archivos:** `core/exchange.py:250-290`.
- **Diseno:** paginar `get_candlesticks`/`get_history_candlesticks` (300/pagina) hacia atras hasta
  `limit`; devolver `timestamp` como ms int (igual que `BacktestClient.get_ohlcv`,
  `backtest.py:188-206`). Rate-limit friendly (sleep entre paginas).
- **Riesgo:** metodo compartido con Pro Trend (congelado) — Pro Trend usa limits <=300 hoy?
  Verificarlo con grep antes; si usa mas, ya estaba roto en vivo tambien.
- **Validar:** test de paridad: mismas 6000 velas por API vs por cache → indicadores identicos.
- **Cierre:** `python -c` de humo contra OKX real devuelve 6000 filas con timestamp ms.

### F13. Swing en la ruta `start` + RiskManager
- **Archivos:** `main.py:209-233` (rama `swing_allocator`), `strategies/swing_allocator.py`
  (aceptar `risk_manager=None` opcional; consultar `check_daily_loss` antes de rebalancear).
- **Nota:** ESCRIBIR el codigo no requiere OK; EJECUTAR `start` si (regla del proyecto).
- **Cierre:** `python main.py start --strategy swing --symbol BTC-USDT` en paper arranca, loggea
  el primer target y NO lanza excepciones en 24h.

### F14. Validacion de datos en vivo + controles minimos
- **Objetivo:** los controles operativos que faltan (punto 16 de la auditoria).
- **Acciones:**
  - Validacion de precio anomalo: rechazar tick si |delta| > X% vs ultima vela (config).
  - Kill switch: ya existe `emergency_stop` — anadir comando/atajo documentado para el Swing.
  - Limite de perdida diaria/semanal aplicado al Swing via RiskManager.
  - Log de cada decision: el `_rebalance_log` ya existe — persistirlo tambien en paper/live
    (hoy solo lo escribe el backtest via `write_swing_journal`).
- **Cierre:** checklist de controles en SESSION.md con estado por control.

### F15. Test de paridad backtest vs paper
- **Objetivo:** mismo dia, mismos datos → mismo target.
- **Diseno:** script que corre `_compute_target` con el cliente real (paper) y con BacktestClient
  sobre las mismas velas y compara target/senales durante N dias.
- **Cierre:** 30 dias consecutivos sin divergencia de target (tolerancia 0 — es determinista).

---

## FASE 5 — Riesgo de cola y sizing (hallazgos C3, C8)

### F16. Stress USDT depeg
- **Objetivo:** cuantificar el riesgo del "activo refugio" (hasta 80% en USDT justo en bear).
- **Herramienta:** script sobre la equity reconstruida: aplicar -5% y -10% al saldo USDT en
  2018-06 y 2022-06 (mitad del bear) → impacto en final/CAGR/DD.
- **Mitigacion a evaluar (solo diseno, no implementar aun):** diversificar el lado estable
  (USDC/T-bills via exchange) — anotar en pendientes.
- **Cierre:** numeros en AUDITORIA + decision de si se acepta el riesgo.

### F17. Recomendacion de sizing formal
- **Objetivo:** dimensionar cuanto capital real puede ir a esta estrategia.
- **Base:** DD p95 del bootstrap (F7), no el historico. Regla: capital asignado tal que
  (DD_p95 x capital) sea una perdida tolerable de verdad.
- **Marcos:** conservador = 10-20% del patrimonio cripto; moderado = 30-50%; agresivo = 100%
  del capital destinado a BTC (sustituye al B&H). Nunca apalancamiento. Un solo exchange =
  riesgo de custodia: considerar retirar excedente por encima de un umbral.
- **Cierre:** parrafo de sizing en SESSION.md firmado como decision.

---

## FASE 6 — Benchmarks y monitorizacion de degradacion

### F18. Anadir DCA y EMA200D-simple a `baselines`
- **Objetivo:** que el Swing se compare contra lo que debe batir un allocator.
- **Archivos:** comando `baselines` en `main.py`.
- **Benchmarks:** DCA semanal (mismo capital total), EMA200D long/flat simple, 60/40 BTC/USDT
  rebalanceado mensual (la version "sin senales" del propio Swing — el control perfecto).
- **Cierre:** tabla comparativa en README con CAGR/DD/Calmar/underwater/trades de los 3 + v4.
  Si v4 no bate al 60/40 rebalanceado en Calmar, decirlo en el README.

### F19. Panel de degradacion para paper/live
- **Objetivo:** detectar cuando el sistema deja de comportarse como el backtest.
- **Metricas (rolling):** slippage medio real vs 5bps asumido; coste por rebalanceo; numero de
  rebalanceos por trimestre vs backtest (~3.1/trimestre); tracking error vs simulacion paralela
  con las mismas velas; DD actual vs distribucion del bootstrap.
- **Reglas de accion:**
  - Slippage real > 2x asumido durante 5 rebalanceos → revisar ejecucion (ordenes TWAP).
  - Frecuencia de rebalanceo > 2x backtest → posible ping-pong nuevo → pausar y analizar.
  - Divergencia de target vs simulacion paralela → BUG → apagar (kill switch).
  - DD > p95 bootstrap → reducir asignacion al nivel conservador; DD > p99 → apagar y re-evaluar.
- **Cierre:** implementado como reporte periodico (`tools/degradation_report.py`) sobre el
  journal de paper.

---

## QUE NO HACER (vigente durante todo el plan)

- No re-optimizar NADA sobre 2015-2026 (cada consulta degrada la validez restante).
- No resucitar VIX/MVRV/Pi-Cycle/RSI/MACD4H/funding/DXY.
- No vol-targeting, no ATR de-risk intradia, no ML, no multi-asset, no shorts, no apalancamiento.
- No anadir logica al `bull_peak_ema50_cap` (candidato a RETIRAR en F6, no a extender).
- No tocar `pro_trend.py` (congelado) ni los defaults de fase en F4 (solo parametrizar).

## ORDEN RECOMENDADO Y ESTADO

| Paso | Fase | Depende de | Estado |
|------|------|-----------|--------|
| 0.1 Commit + tag v4 | 0 | — | [ ] |
| 0.2 Regla out-of-sample | 0 | — | [ ] |
| F1 P&L por cantidades | 1 | 0.1 | [ ] |
| F2 Underwater duration | 1 | — | [ ] |
| F3 Retirar PF de docs | 1 | F1 | [ ] |
| F4 Fases configurables | 2 | 0.1 | [ ] |
| F5 Matriz calendario | 2 | F4 | [ ] parcial (480/600 hechos, ver AUDITORIA) |
| F6 Ablation halving-only extra | 2 | — | [ ] parcial (2015-26 realistic hecho) |
| F7 Bootstrap | 2 | — | [ ] |
| F8 Diarios cerrados | 3 | 0.1 | [ ] |
| F9 Cadencia reloj | 3 | 0.1 | [ ] |
| F10 Fill next-open (medir) | 3 | — | [ ] |
| F11 Menores C7/C9 | 3 | — | [ ] |
| F12 get_ohlcv paginado | 4 | — | [ ] |
| F13 Swing en start | 4 | F12 | [ ] |
| F14 Controles operativos | 4 | F13 | [ ] |
| F15 Paridad backtest/paper | 4 | F13 | [ ] |
| F16 Stress USDT | 5 | — | [ ] |
| F17 Sizing formal | 5 | F7 | [ ] |
| F18 Benchmarks DCA/60-40 | 6 | — | [ ] |
| F19 Panel degradacion | 6 | F15 | [ ] |
