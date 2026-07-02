# AUDITORIA CUANTITATIVA — Swing Allocator v4 + motor de backtest

**Fecha:** 2026-07-02 (sesion 15) | **Auditor:** revision critica interna (Claude)
**Objeto:** `strategies/swing_allocator.py` (v4 default), `core/backtest.py`, contextos externos,
proceso de validacion (sesiones 13-15).
**Baseline auditado:** v4, 2015-01-01 → 2026-01-01, costs realistic:
CAGR +86.2% / Max DD -52.71% / PF 4.43 / 68 trades / final 9.31M desde 10k.
**Journal fuente:** `backtests/journal_swing_allocator_btc_usdt_BTCUSDT_1H_20260702_064622.json`
(reconstruccion de equity validada contra el journal con error relativo max 0.0003%).

---

## DIAGNOSTICO GENERAL

**No es un sistema de trading validado: es una tesis macro de calendario ("vende a halving+540d,
recompra a +900d") con n=2 observaciones independientes, envuelta en infraestructura de backtest
razonablemente limpia.**

Lo bueno: el motor no tiene lookahead material, los costes son robustos hasta x3, spot sin
apalancamiento (sin ruina mecanica), y el proceso (WF, ablations, anclas CAGR/DD) es mejor que la
mayoria de proyectos retail.

Lo malo: el edge entero descansa en 3 salidas por `bear_onset` (ene-2018, nov-2021, oct-2025), el
umbral 540d esta clavado a los techos de 2017/2021 con los que se diseño, esta hardcodeado fuera de
la config y nunca paso por el protocolo de sensibilidad. Las metricas por-trade (PF/WR/expectancy)
estan estructuralmente mal calculadas para un allocator. La ruta live/paper no existe en el codigo.

**Veredicto: prometedor pero no validado. La precision de los parametros centrales es
probablemente sobreajustada aunque la tesis (techo de ciclo ~1.5 anos post-halving) sea
estructural.**

---

## B. RIESGOS GRAVES

### B1. [CRITICO — interpretacion] Concentracion extrema del edge

La estrategia pierde contra B&H en 8 de 11 anos. Tabla reconstruida desde el journal v4
(realistic, fee 0.1% + slip 5bps replicados):

| Anio | Estrategia | B&H | Alpha (ratio) | Max DD | Expo media BTC |
|------|-----------|------|---------------|--------|----------------|
| 2015 | +40.4% | +34.8% | 1.04 | -34% | 0.43 |
| 2016 | +109.6% | +124.2% | 0.94 | -34% | 0.89 |
| 2017 | +1203.7% | +1336.0% | 0.91 | -37% | 0.98 |
| **2018** | **-20.2%** | **-72.9%** | **2.95** | -29% | 0.22 |
| 2019 | +58.0% | +94.3% | 0.81 | -43% | 0.62 |
| 2020 | +258.3% | +302.9% | 0.89 | -34% | 0.81 |
| 2021 | +87.2% | +59.4% | 1.17 | -49% | 0.79 |
| **2022** | **-20.3%** | **-64.5%** | **2.25** | -22% | 0.21 |
| 2023 | +79.6% | +155.7% | 0.70 | -17% | 0.74 |
| 2024 | +80.7% | +120.3% | 0.82 | -30% | 0.91 |
| 2025 | +10.4% | -7.2% | 1.19 | -27% | 0.77 |

- Alpha total vs B&H: **3.40x** (estrategia 9.28M vs B&H 2.74M).
- **Excluyendo 2017-2018 el alpha cae a 1.27x.** Excluyendo 2020-2021: 3.26x (esos anos no son
  la fuente).
- Atribucion multiplicativa por tipo de tramo (senal activa al abrir el tramo):
  - tramos `bear_onset`: **x10.99**
  - tramos `post/bull_peak`: x0.75
  - tramos `regime_bear`: x0.51
  - otros: x0.83
  - => TODO el alpha viene de bear_onset; el resto combinado destruye valor (x0.32 agregado).
- Mayores tramos de alpha: 2021-11-02→2022-10-28 (btc 30%, x2.41), 2018-04-13→2018-12-07
  (btc 20%, x2.11), COVID 2020-03-09→03-13 (x1.58), 2018-01-02→02-04 (x1.51),
  2025-10-13→2026-01-01 (x1.22).
- El evento de 2025 NO es out-of-sample: la regla se diseno en 2026 con datos que lo incluyen.
- n efectivo = 2-3 eventos. El proximo dato independiente llega una vez por ciclo (~4 anos).

### B2. [CRITICO — overfitting] El umbral bear_onset=540d es un fit de 2 puntos y es fragil

- Halving 2016-07-09 + 540d = **2017-12-31** (techo real: 2017-12-17).
- Halving 2020-05-11 + 540d = **2021-11-02** (techo real: 2021-11-10).
- Hardcodeado en `strategies/macro_context.py:186-195` — fuera de config, **nunca entro en
  sensitivity ni en walk-forward** (los WF validaron knobs perifericos con el calendario fijo).

Sensibilidad ejecutada 2026-07-02 (2015-2026 realistic, resto default v4):

| bear_onset empieza en | CAGR | Max DD | PF | Trades |
|----------------------|------|--------|-----|--------|
| 480d | +75.5% (-10.7pp) | -52.7% | 4.47 | 62 |
| **540d (default)** | **+86.2%** | **-52.7%** | 4.43 | 68 |
| 600d | +77.4% (-8.8pp) | **-66.1%** (+13.4pp) | 2.34 | 75 |

±60 dias de error en el reloj cuesta ~10pp de CAGR o lleva el Max DD a -66%.
A favor: incluso perturbado sigue batiendo B&H (+66.6% CAGR) con menos DD — el SIGNO del edge
sobrevive; la magnitud no.

### B3. [ALTO — metricas] PF/win-rate/expectancy/median estructuralmente mal calculados

`core/backtest.py:616-639` (`_compute_trade_pnl`):
- Empareja cada venta con la compra abierta mas antigua **sin igualar cantidades**
  (PnL = delta_precio * qty_venta aunque la compra fuera de otro tamano).
- Descarta ventas sin lote abierto y compras nunca cerradas.
- El docstring dice "LIFO" pero `lots.pop(0)` es FIFO.

Para Pro Trend (entrada/salida simetrica) es aproximadamente valido; para rebalanceos parciales
del allocator es ruido. Evidencia: PF de las variantes de hoy = 4.43 / 2.34 / 7.25 / **117.8**
con cambios menores de config. CAGR/DD/equity NO estan afectados (salen de balances).
**No citar PF del Swing en README/decisiones.**

### B4. [ALTO — operativa] Paridad backtest→live rota; el Swing no puede hacer ni paper

1. `main.py:209-233` (`_instantiate_strategy`): no hay rama `swing_allocator` →
   `start --strategy swing` cae en "Tipo de estrategia desconocido".
2. `core/exchange.py:250-270`: `get_ohlcv` pasa `limit=6000` a `get_candlesticks` SIN paginar;
   OKX capea ese endpoint a ~300 velas → `len(df) < 500` → `_get_daily_indicators` devuelve None
   → en vivo operaria **solo con senales de halving, silenciosamente** (la excepcion se traga en
   `swing_allocator.py:252-258`).
3. Mismatch de interfaz: `BacktestClient.get_ohlcv` devuelve `timestamp` en ms (int);
   `OKXClient.get_ohlcv` devuelve `pd.Timestamp` → `resample_to_daily` (`indicators.py:108`,
   `unit="ms"`) se comporta distinto. El claim "imita OKXClient al 100%" es falso en el metodo
   mas usado por el Swing.
4. `RiskManager` (daily loss, emergency stop, blacklist) existe y esta cableado para
   adaptive/pro/scalp; `SwingAllocatorBot.__init__` ni lo acepta.

### B5. [ALTO — proceso] Data snooping: no existe holdout real

v1→v2→v3→v4 se seleccionaron sobre la misma ventana 2015-2026 que luego valida el go/no-go.
La "ventana secundaria" 2018-2026 es un subconjunto. Cada iteracion de sesiones 13-15 que
descarto variantes "porque empeoran 2015-2026" fue una consulta mas al mismo dataset. El WF 4/4
es lo mejor del proceso, pero valido los knobs perifericos, no el calendario (fijo en los folds).

---

## C. PROBLEMAS MEDIOS

| # | Problema | Ubicacion | Detalle |
|---|----------|-----------|---------|
| C1 | Fill al close de la vela de decision | `backtest.py:326` (`_fill_market` usa `current_bar.close`) | Decide con el close de la barra i y ejecuta a ese close ± slippage. Estandar pero optimista. Impacto despreciable a escala 540d. |
| C2 | Indicadores diarios usan el dia en curso parcial | `swing_allocator.py:474-508` | EMA50/200D, RSI, ADX, Pi Cycle incluyen el dia incompleto (solo `ema50d_closed` excluye). No es lookahead (computable en tiempo real) pero viola la regla invariante #1. La cache diaria se congela en la primera barra del dia. |
| C3 | Slippage independiente del tamano | `backtest.py:326-333` | Notional total operado 87.2M USDT; rebalanceos finales de millones. Irrelevante a 10-100k reales; no extrapolar la curva compuesta a tamano grande. |
| C4 | `max_dd_duration` mide peak→trough, no underwater | `backtest.py:656-672` | Reporta 260d; el tiempo real bajo el agua de 2018/2022 son 2-3 anos. Infrarreportado ~4x. |
| C5 | Empalme Bitstamp USD 2014-2017 | cache canonico 102931 | La ventana primaria simula un par (BTC/USDT en OKX) que no existia antes de ~2017. Mitigante: la estrategia PIERDE alpha en ese tramo (2016: 0.94, 2017: 0.91), no lo infla — pero si infla el CAGR headline. |
| C6 | Cadencia `_bar_count % 4` no alineada a reloj | `swing_allocator.py:180` | Depende del offset de warmup y de huecos → contribuye a la sensibilidad al punto de inicio. |
| C7 | "EMA200D" es una EMA truncada | `swing_allocator.py:107` (`lookback_hours=6000`) | ~250 dias de ventana: no converge; el valor depende del tamano de ventana. Determinista, pero cambiar `lookback_hours` cambia las senales. |
| C8 | Riesgo de cola real | diseno | Sin apalancamiento ni stops → flash crash -20% cuesta 20% x exposicion, sin ruina mecanica. Riesgos reales: **USDT depeg** (hasta 80% en USDT justo en bear), custodia 100% en un exchange, velas corruptas sin validacion de precio anomalo. |
| C9 | B&H benchmark sin coste de compra | `backtest.py:476-478` | Sesgo a FAVOR del benchmark. Menor. |

---

## RESULTADOS DE SENSIBILIDAD Y ABLATION (ejecutados 2026-07-02)

Todos: 2015-01-01 → 2026-01-01, costs realistic. Baseline v4: CAGR +86.2% / DD -52.71% / PF 4.43.

| Variante | CAGR | Max DD | PF | Trades | Lectura |
|----------|------|--------|-----|--------|---------|
| bear_onset 480d | +75.5% | -52.7% | 4.47 | 62 | fragil (B2) |
| bear_onset 600d | +77.4% | -66.1% | 2.34 | 75 | fragil (B2) |
| rebalance_threshold 0.15 | +82.6% | -54.1% | 4.08 | 46 | estable |
| min_days_between_rebalance 5 | +83.8% | -55.9% | 2.78 | 59 | estable |
| base_btc_pct 0.55 | +81.7% | -50.5% | 7.25 | 52 | estable (PF absurdo → confirma B3) |
| **halving-only** (use_regime=false) | **+73.7%** | **-50.9%** | 117.8 | **13** | el 85% del sistema es el calendario |
| **regime-only** (use_halving=false) | +59.0% | -65.2% | 2.60 | 60 | **pierde contra B&H (+66.6%)** |

Sensibilidad a costes (mismos rebalanceos, costes reaplicados):

| Costes | Final | CAGR |
|--------|-------|------|
| x1 (fee 0.10% + slip 5bps) | 9.28M | +86.1% |
| x2 | 9.08M | +85.7% |
| x3 | 8.87M | +85.3% |

**Robusto a costes** (churn bajo: 138 rebalanceos en 11 anos). Funding no aplica (spot).
Maker/taker: asume taker 0.1% (correcto tier base OKX). Fills parciales/perdidos: no modelados,
pero con market orders sobre BTC-USDT a tamano retail es aceptable.

---

## LO QUE ESTA BIEN (verificado, sin hallazgo)

- Lookahead: `ema50d_closed` correcto; 4H excluye bloque en curso (`swing_allocator.py:538`);
  halving usa solo fechas pasadas; MVRV/VIX/DXY/funding con offset dia/sesion anterior (y ademas
  desactivados). Sin resample centrado, sin shift negativo.
- Warmup excluido de la simulacion (`main.py:313-316`, timestamp < from_ts).
- Cache OHLCV determinista, escritura atomica, no cachea descargas truncadas,
  `contiguity_report` avisa de huecos (`data/ohlcv_cache.py`).
- Backtest continuo, sin reinicio de balance.
- Buffer 0.9965 en compras cubre fee+slip en los 3 modos (`swing_allocator.py:403`).
- Equity curve con timestamps UTC reales; CAGR/DD calculados sobre balances (no afectados por B3).
- La mayoria de senales-basura ya fueron descartadas por sensitivity (MVRV, RSI, Pi Cycle, VIX,
  MACD 4H, funding, DXY = False). Poca complejidad decorativa residual.

---

## CONCLUSION DIRECTA

**No meter dinero real. Paper trading hoy es imposible (la ruta live del Swing no existe).**

El backtest es honesto en costes y ejecucion, pero lo validado es UNA regla de calendario que
acerto los 2 techos con los que fue disenada. Como *tilt* de ciclo sobre una cartera B&H de BTC,
con tamano dimensionado para tolerar -55% (historico) a -80% (1.5x historico, plausible), la
tesis es defendible. Como "estrategia de CAGR +86%", no: ese numero es 2017 mas dos salidas
afortunadas compuestas.

Orden correcto: congelar v4 → construir y verificar ruta paper → matriz de fases + bootstrap →
aceptar que el veredicto real del edge no llega hasta el proximo ciclo.

Ver plan de ejecucion paso a paso en `PLAN_MEJORA_AUDITORIA.md`.
