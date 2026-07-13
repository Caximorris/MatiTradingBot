# Swing Allocator — Auditorías y plan de mejora

Documento consolidado. Reúne las tres piezas de la auditoría cuantitativa del Swing Allocator
(antes en `AUDITORIA_SWING_V4.md`, `PLAN_MEJORA_AUDITORIA.md` y
`AUDITORIA_SWING_V5_POST_IMPLEMENTACION.md`). Contenido íntegro, sin recortes; solo reorganizado en
tres secciones para no tener tres ficheros sueltos en la raíz.

> **Estado actual (2026-07-13):** este documento conserva las auditorias historicas v4/v5.
> Swing v6-2 es ahora el default congelado; v5 permanece como control/rollback. La decision y
> las anclas vigentes estan en `docs/swing/v6-plan.md` y `SESSION.md`.

**Índice**

1. [Auditoría v4 — hallazgos B1–B5 / C1–C9](#1-auditoria-swing-v4)
2. [Plan de mejora F1–F19 (remediación de la auditoría)](#2-plan-de-mejora-f1-f19)
3. [Auditoría v5 post-implementación (freeze)](#3-auditoria-swing-v5-post-implementacion)

---

<a id="1-auditoria-swing-v4"></a>
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

**Actualizacion F1 (2026-07-02):** `_compute_trade_pnl_acb` sustituye el pairing FIFO por coste medio
ponderado con fees prorrateados y deja `legacy_fifo` como selector interno. Smoke v4 post-F1:
final $9.307M, CAGR +86.2%, Max DD -52.71%, underwater 922d. El PF ACB sube a 88.38 porque mide
realizacion contable de rebalanceos, no calidad de decision del allocator. Conclusion: F1 corrige
la aritmetica, pero PF/WR/expectancy del Swing siguen fuera de las anclas.

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

### Actualizacion F5-F11 (2026-07-02)

Matriz calendario completa sobre v4 congelado (`daily_on_closed_only=false`), 2015-2026 realistic:

| Variante | CAGR | Max DD | Trades | Lectura |
|---|---:|---:|---:|---|
| default 180/540/900 | +86.11% | -52.71% | 70 | baseline congelado |
| post_end 120 | +86.00% | -52.71% | 72 | estable |
| post_end 240 | +86.55% | -52.71% | 68 | estable |
| onset_end 800 | +83.59% | -54.05% | 70 | menor pero sobrevive |
| onset_end 1000 | +86.51% | -52.71% | 67 | estable |
| shift -30d | +80.83% | -52.71% | 69 | fragil en magnitud |
| shift +30d | +81.73% | -57.53% | 73 | fragil en DD |
| shift -60d | +72.86% | -52.71% | 67 | edge sobrevive, CAGR cae fuerte |
| shift +60d | +77.40% | -66.08% | 77 | edge sobrevive, DD se degrada |

Conclusion F5: el signo del edge sobrevive en todas las variantes frente a B&H, pero la magnitud
depende demasiado del reloj: no se cambia ningun umbral.

F6 halving-only extra:

| Ventana | Config | CAGR | Max DD | Final | `btc_vs_bnh` | Decision |
|---|---|---:|---:|---:|---:|---|
| 2018-2026 realistic | v4 congelado | +47.59% | -53.42% | $225.2k | 0.8641 | mantener |
| 2018-2026 realistic | halving-only | +41.66% | -50.91% | $162.2k | 0.6410 | rechazar |
| 2015-2026 conservative | v4 congelado | +85.65% | -52.86% | $9.03M | 0.8082 | mantener |
| 2015-2026 conservative | halving-only | +73.56% | -50.91% | $4.31M | 0.4004 | rechazar |

F7 bootstrap mensual de equity v4 congelado, x1000: CAGR p05/p50/p95 = +45.93% / +85.39% /
+139.94%; MaxDD p50/p95/p99 = -53.01% / -68.31% / -74.34%. Sizing real debe dimensionarse con
p95/p99, no con el DD historico.

F8-F10:

| Check | CAGR | Max DD | Final | Decision |
|---|---:|---:|---:|---|
| v4 congelado | +86.11% | -52.71% | $9.28M | referencia |
| `daily_on_closed_only=true` | +85.84% | -52.73% | $9.14M | ADOPTADO por regla anti-lookahead |
| `clock_aligned_cadence=true` | +84.62% | -52.99% | $8.50M | NO adoptar; no reduce offset |
| `fill_next_open=true` | +86.08% | -52.71% | $9.27M | medir, no cambiar default |

F11: B&H incluye coste de compra; `lookback_hours` documenta que la EMA200D del Swing es truncada.

### Actualizacion operativa F12-F17 (2026-07-02)

- F12: `OKXClient.get_ohlcv` pagina OKX hasta el `limit` pedido y devuelve `timestamp` como ms `int64`
  para igualar a `BacktestClient`. Smoke con OKX real: 6000 velas 1H y dtype int64.
- F13: `start` ya instancia Swing y pasa `RiskManager`; las compras se bloquean si hay daily-loss,
  las ventas defensivas no. No se ejecuto `start` porque requiere OK explicito y observacion 24h.
- F14: control de precio anomalo (`max_price_jump_pct=0.25`), OHLCV insuficiente bloquea decisiones
  live, kill switch existente (`main.py stop`) y persistencia JSONL de rebalanceos paper/live.
- F16 stress USDT current default:

| Shock | Perdida aplicada | CAGR | Max DD | Final |
|---|---:|---:|---:|---:|
| baseline | $0 | +85.84% | -52.73% | $9.14M |
| 2018-06 depeg -5% | $13.4k | +85.06% | -52.73% | $8.72M |
| 2018-06 depeg -10% | $26.8k | +84.37% | -52.73% | $8.37M |
| 2022-06 depeg -5% | $120.1k | +85.09% | -52.73% | $8.74M |
| 2022-06 depeg -10% | $240.1k | +84.30% | -52.73% | $8.34M |

F17 sizing: usar MaxDD p95/p99 bootstrap (-68%/-74%) para asignacion real; un sizing que solo tolera
-55% esta subdimensionado.

F15/F18/F19 parciales:
- `tools/swing_parity_check.py`: check puntual 2026-07-02 12:00 UTC OK, target live/backtest 0.2000
  con senales `regime_bear;halving_bear_onset`. No sustituye los 30 dias de paper.
- `tools/swing_benchmarks.py`: Swing current supera controles simples en 2015-2026 realistic:
  60/40 mensual $540k/CAGR +43.71%/DD -65.01%; EMA200D $1.47M/+57.36%/-74.93%; DCA semanal
  $539k/+43.69%/-79.06%. Falta integrarlo en el comando `baselines`.
- `tools/degradation_report.py`: reporte JSONL para paper/live creado; sin datos live aun.

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


---

<a id="2-plan-de-mejora-f1-f19"></a>

# PLAN DE MEJORA — auditoria Swing v4 (2026-07-02)

Fuente: `AUDITORIA_SWING_V4.md`. Cada paso tiene objetivo, archivos, como validar y criterio de
cierre. Orden pensado para resolver primero lo que cambia decisiones (metricas y validez) y
despues lo operativo. Marcar `[x]` al cerrar cada paso y anotar resultado.

> **PLAN CERRADO (2026-07-02, sesion 16).** Todo lo ejecutable sin paper/live esta hecho; el
> resultado es **Swing v5 post-audit** (= v4 + `daily_on_closed_only=True`), congelado como default.
> Anclas v5: 2015-26 realistic +85.84% CAGR / -52.73% DD; 2018-26 +47.14% / -53.72%; conservative
> +85.40% / -52.88%. Auditoria post-implementacion: `AUDITORIA_SWING_V5_POST_IMPLEMENTACION.md`.
> Quedan abiertos SOLO los cierres que requieren tiempo de paper: F13 (24h runtime), F15 (paridad
> 30d), F19 (datos live) y la integracion opcional de benchmarks en `main.py baselines` (F18).

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
- **Resultado 2026-07-02:** implementado `_compute_trade_pnl_acb` + selector `trade_pnl_method`.
  Smoke v4: equity identica (final $9.307M, CAGR +86.2%, DD -52.71%). PF ACB = 88.38; conclusion:
  la aritmetica queda corregida, pero PF del Swing sigue siendo contable y no se usa como ancla.

### F2. Underwater duration real (hallazgo C4)
- **Objetivo:** reportar el tiempo bajo el agua (peak→recovery), no solo peak→trough.
- **Archivos:** `core/backtest.py` — nueva metrica `underwater_days` junto a la actual;
  `summary_rows()` muestra ambas.
- **Cierre:** smoke v4 reporta ambas; esperar ~900-1000d para el peor periodo (2021-2024).
- **Resultado 2026-07-02:** smoke v4 reporta 260d peak->trough y 922d peak->recovery.

### F3. Dejar de citar PF del Swing en docs
- **Objetivo:** que README/SESSION no anclen decisiones a una metrica rota.
- **Archivos:** `README.md`, `SESSION.md` — nota "PF del Swing = artefacto del pairing hasta F1".
- **Cierre:** grep de "PF 4.43" en docs devuelve solo menciones historicas anotadas.
- **Resultado 2026-07-02:** README y CLI ya no presentan PF del Swing como veredicto.

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
- **Resultado 2026-07-02:** tabla completa versionada via `tools/sens_phases.py`. El signo sobrevive
  en todas, pero shift -60d cae a +72.86% CAGR y shift +60d sube DD a -66.08%; no se cambian defaults.

### F6. Ablation halving-only en ventanas/costes restantes
- **Objetivo:** decidir si `use_regime` gana su lugar (aporta +12.5pp CAGR en 2015-26 pero la
  atribucion por tramos del regime es destructiva; halving-only: 73.7%/-50.9% con 13 trades).
- **Runs:** halving-only vs v4 en 2018-2026 realistic y en 2015-2026 conservative.
- **Decision posible:** si regime no aporta fuera del tramo Bitstamp, considerar "v5 = v4 sin
  regime" como candidata SIMPLIFICADORA (menos parametros, menos trades, menos DD) — esto es
  reduccion de complejidad, permitida aunque la ventana este cerrada, si NO empeora las anclas.
- **Cierre:** decision documentada en SESSION.md (mantener regime / retirar regime).
- **Resultado 2026-07-02:** mantener `use_regime=True`. Halving-only pierde CAGR y BTC acumulado en
  2018 realistic y 2015 conservative; no califica como simplificacion.

### F7. Bootstrap por bloques de la equity v4
- **Objetivo:** intervalo de confianza del Max DD (esperar -70/-80% en p95) y del CAGR.
- **Herramienta:** `tools/bootstrap_equity.py` — bloques mensuales de retornos de la equity v4,
  resampleo con reemplazo x1000, distribucion de CAGR/MaxDD.
- **Cierre:** percentiles documentados en AUDITORIA; el sizing de FASE 5 se dimensiona con p95,
  no con el historico.
- **Resultado 2026-07-02:** `tools/bootstrap_equity.py` x1000: MaxDD p95 -68.31%, p99 -74.34%.

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
- **Resultado 2026-07-02:** ADOPTADO `daily_on_closed_only=True`. Impacto aislado menor
  (CAGR +85.84%, DD -52.73%) y corrige regla invariante #1. Rollback: False.

### F9. Cadencia alineada a reloj (C6)
- **Objetivo:** eliminar la dependencia del offset de warmup (sensibilidad al punto de inicio).
- **Archivos:** `swing_allocator.py:179-181` — evaluar cuando `current_time().hour % 4 == 0`
  en vez de `_bar_count % 4`, tras flag `clock_aligned_cadence: bool = True`.
- **Validar:** backtest aislado; ademas re-run con from 2015-01-02 (offset +1 dia) → el resultado
  deberia moverse MENOS que antes.
- **Cierre:** sensibilidad al punto de inicio medida antes/despues y documentada.
- **Resultado 2026-07-02:** MEDIDO y NO adoptado. CAGR +84.62%, DD -52.99%; offset 2015-01-02 no
  mejora frente a v4 congelado.

### F10. Fill en la vela siguiente (C1) — solo medir
- **Objetivo:** cuantificar el optimismo del fill al close de la vela de decision.
- **Accion:** modo opcional `fill_next_open` en `BacktestClient._fill_market` (fila en la barra
  siguiente al open ± slippage). Correr v4 con el una vez.
- **Regla:** si el impacto es <1pp CAGR (esperado a escala 540d), documentar y NO cambiar el
  default (evita romper comparabilidad). Si es mayor, adoptar y re-anclar.
- **Cierre:** delta documentado en AUDITORIA.
- **Resultado 2026-07-02:** `BacktestClient(fill_next_open=True)` implementado. Impacto medido:
  CAGR +86.08%, DD -52.71%; default no cambia.

### F11. Menores: B&H con coste (C9) + doc de EMA truncada (C7)
- `backtest.py:476-478`: aplicar fee+slip de una compra al benchmark B&H.
- `swing_allocator.py:107`: comentario documentando que la "EMA200D" es truncada a la ventana
  `lookback_hours` y que cambiar ese valor cambia las senales.
- **Cierre:** ambos triviales, un commit.
- **Resultado 2026-07-02:** B&H incluye coste de compra; comentario C7 anadido.

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
- **Resultado 2026-07-02:** implementado y validado contra OKX real: 6000 filas 1H, `timestamp`
  dtype `int64`.

### F13. Swing en la ruta `start` + RiskManager
- **Archivos:** `main.py:209-233` (rama `swing_allocator`), `strategies/swing_allocator.py`
  (aceptar `risk_manager=None` opcional; consultar `check_daily_loss` antes de rebalancear).
- **Nota:** ESCRIBIR el codigo no requiere OK; EJECUTAR `start` si (regla del proyecto).
- **Cierre:** `python main.py start --strategy swing --symbol BTC-USDT` en paper arranca, loggea
  el primer target y NO lanza excepciones en 24h.
- **Resultado 2026-07-02:** codigo listo: `_instantiate_strategy` soporta Swing y pasa RiskManager;
  compras bloqueadas por `check_daily_loss`, ventas permitidas. Runtime 24h pendiente de OK explicito.

### F14. Validacion de datos en vivo + controles minimos
- **Objetivo:** los controles operativos que faltan (punto 16 de la auditoria).
- **Acciones:**
  - Validacion de precio anomalo: rechazar tick si |delta| > X% vs ultima vela (config).
  - Kill switch: ya existe `emergency_stop` — anadir comando/atajo documentado para el Swing.
  - Limite de perdida diaria/semanal aplicado al Swing via RiskManager.
  - Log de cada decision: el `_rebalance_log` ya existe — persistirlo tambien en paper/live
    (hoy solo lo escribe el backtest via `write_swing_journal`).
- **Cierre:** checklist de controles en SESSION.md con estado por control.
- **Resultado 2026-07-02:** precio anomalo, OHLCV insuficiente live, kill switch y persistencia JSONL
  implementados. Perdida semanal no existe aun en RiskManager; queda fuera de este cierre.

### F15. Test de paridad backtest vs paper
- **Objetivo:** mismo dia, mismos datos → mismo target.
- **Diseno:** script que corre `_compute_target` con el cliente real (paper) y con BacktestClient
  sobre las mismas velas y compara target/senales durante N dias.
- **Cierre:** 30 dias consecutivos sin divergencia de target (tolerancia 0 — es determinista).
- **Resultado 2026-07-02:** herramienta `tools/swing_parity_check.py`; check puntual OK contra OKX
  real. Cierre de 30 dias sigue pendiente de paper.

---

## FASE 5 — Riesgo de cola y sizing (hallazgos C3, C8)

### F16. Stress USDT depeg
- **Objetivo:** cuantificar el riesgo del "activo refugio" (hasta 80% en USDT justo en bear).
- **Herramienta:** script sobre la equity reconstruida: aplicar -5% y -10% al saldo USDT en
  2018-06 y 2022-06 (mitad del bear) → impacto en final/CAGR/DD.
- **Mitigacion a evaluar (solo diseno, no implementar aun):** diversificar el lado estable
  (USDC/T-bills via exchange) — anotar en pendientes.
- **Cierre:** numeros en AUDITORIA + decision de si se acepta el riesgo.
- **Resultado 2026-07-02:** script `tools/stress_usdt_depeg.py`; depeg -10% en 2018/2022 deja CAGR
  ~+84.3% y final ~$8.34-8.37M. Riesgo aceptado solo con sizing/custodia prudente.

### F17. Recomendacion de sizing formal
- **Objetivo:** dimensionar cuanto capital real puede ir a esta estrategia.
- **Base:** DD p95 del bootstrap (F7), no el historico. Regla: capital asignado tal que
  (DD_p95 x capital) sea una perdida tolerable de verdad.
- **Marcos:** conservador = 10-20% del patrimonio cripto; moderado = 30-50%; agresivo = 100%
  del capital destinado a BTC (sustituye al B&H). Nunca apalancamiento. Un solo exchange =
  riesgo de custodia: considerar retirar excedente por encima de un umbral.
- **Cierre:** parrafo de sizing en SESSION.md firmado como decision.
- **Resultado 2026-07-02:** sizing documentado en SESSION con MaxDD p95/p99 bootstrap (-68%/-74%).

---

## FASE 6 — Benchmarks y monitorizacion de degradacion

### F18. Anadir DCA y EMA200D-simple a `baselines`
- **Objetivo:** que el Swing se compare contra lo que debe batir un allocator.
- **Archivos:** comando `baselines` en `main.py`.
- **Benchmarks:** DCA semanal (mismo capital total), EMA200D long/flat simple, 60/40 BTC/USDT
  rebalanceado mensual (la version "sin senales" del propio Swing — el control perfecto).
- **Cierre:** tabla comparativa en README con CAGR/DD/Calmar/underwater/trades de los 3 + v4.
  Si v4 no bate al 60/40 rebalanceado en Calmar, decirlo en el README.
- **Resultado 2026-07-02:** herramienta parcial `tools/swing_benchmarks.py` con DCA semanal,
  EMA200D long/flat y 60/40 mensual. Falta integrar en `main.py baselines` y README.

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
- **Resultado 2026-07-02:** `tools/degradation_report.py` implementado sobre JSONL live/paper.
  Sin datos paper/live aun; slippage real requiere enriquecer eventos de ejecucion.

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
| 0.1 Commit + tag v4 | 0 | — | [x] tag `swing-v4-frozen` en 06395ff; rama local sigue ahead por docs auditoria |
| 0.2 Regla out-of-sample | 0 | — | [x] |
| F1 P&L por cantidades | 1 | 0.1 | [x] ACB + legacy flag; PF Swing sigue no-ancla |
| F2 Underwater duration | 1 | — | [x] |
| F3 Retirar PF de docs | 1 | F1 | [x] |
| F4 Fases configurables | 2 | 0.1 | [x] defaults validados por smoke v4 |
| F5 Matriz calendario | 2 | F4 | [x] |
| F6 Ablation halving-only extra | 2 | — | [x] mantener regime |
| F7 Bootstrap | 2 | — | [x] |
| F8 Diarios cerrados | 3 | 0.1 | [x] adoptado default True |
| F9 Cadencia reloj | 3 | 0.1 | [x] medido, no adoptado |
| F10 Fill next-open (medir) | 3 | — | [x] medido, default igual |
| F11 Menores C7/C9 | 3 | — | [x] |
| F12 get_ohlcv paginado | 4 | — | [x] |
| F13 Swing en start | 4 | F12 | [ ] codigo listo; falta OK + 24h paper |
| F14 Controles operativos | 4 | F13 | [x] parcial sin perdida semanal |
| F15 Paridad backtest/paper | 4 | F13 | [ ] check puntual OK; faltan 30 dias |
| F16 Stress USDT | 5 | — | [x] |
| F17 Sizing formal | 5 | F7 | [x] |
| F18 Benchmarks DCA/60-40 | 6 | — | [x] script + tabla en README; integracion en CLI `baselines` opcional pendiente |
| F19 Panel degradacion | 6 | F15 | [ ] script listo; faltan datos paper/live |


---

<a id="3-auditoria-swing-v5-post-implementacion"></a>

# AUDITORIA POST-IMPLEMENTACION — Swing Allocator v5 (2026-07-02)

Auditoria del diff completo desde el tag `swing-v4-frozen` (06395ff): cambios F1-F19 del
`PLAN_MEJORA_AUDITORIA.md`. Objetivo: verificar que los fixes NO introducen sesgos nuevos
(lookahead, leakage, costes, timezone, gaps) y que los hallazgos B1-B5/C1-C9 de
`AUDITORIA_SWING_V4.md` quedaron resueltos.

**Alcance:** `core/backtest.py`, `core/exchange.py`, `main.py`, `strategies/macro_context.py`,
`strategies/swing_allocator.py`, tests y `tools/` nuevos. El nucleo de decision del Swing
(v4 estructural) NO se re-audita: quedo auditado en `AUDITORIA_SWING_V4.md` y esta congelado.

**Definicion de v5:** v4 estructural + `daily_on_closed_only=True` (F8 — UNICO delta de
comportamiento). El resto de cambios son motor/metricas/operativa live y no tocan senales.

---

## VEREDICTO GLOBAL

**APTO PARA FREEZE.** Ningun hallazgo CRITICO ni ALTO. Los cambios F1-F19 no introducen
lookahead ni leakage; los dos unicos deltas que tocan la simulacion (F8 y el coste del B&H F11)
van en direccion CONSERVADORA (empeoran ligeramente al Swing / al benchmark de forma justa).
Quedan 2 hallazgos MEDIO (riesgo latente, no activo en el dataset canonico) y 4 BAJO.

Tests: 88/88 en verde (`python -m pytest tests -q`), incluyendo `test_backtest_pnl.py` (F1)
y `test_swing_allocator_controls.py` (F14).

---

## HALLAZGOS NUEVOS (introducidos por la implementacion)

### M1. [MEDIO] `set_phase_bounds` muta estado GLOBAL de modulo desde el constructor del bot

- **Donde:** `strategies/swing_allocator.py` (`SwingAllocatorBot.__init__`) →
  `strategies/macro_context.py` (`set_phase_bounds`, globales `PHASE_*`).
- **Que pasa:** cada instancia del Swing re-escribe los umbrales de fase PARA TODO EL PROCESO.
  `halving_phase` tambien lo consume Pro Trend: un Swing con fases custom (sensitivity) cambiaria
  las fases de Pro Trend en el mismo proceso. Dos backtests Swing concurrentes con fases distintas
  en un mismo proceso se pisarian.
- **Por que no es ALTO:** en produccion los defaults son identicos (180/540/900) y el setter es
  no-op + hay warning log si se cambian. Solo afecta a harnesses de sensitivity multi-config
  en proceso unico.
- **Accion recomendada (no urgente):** pasar los umbrales por parametro a `get_macro_signal`
  en vez de globales, o documentar "un proceso = una config de fases" en los tools (hoy los
  tools cumplen esto).

### M2. [MEDIO] El filtro de tick anomalo (F14) corre TAMBIEN en backtest

- **Donde:** `strategies/swing_allocator.py` (`_market_data_ok`), llamado antes de `_initialize`
  y de cada evaluacion; `max_price_jump_pct=0.25` aplica igual con `BacktestClient`.
- **Medicion (2026-07-02):** salto 1H maximo close-to-close en el dataset canonico BTC
  (102931 velas) = **19.18%** (2020-03-12 10:00, COVID) → el filtro NUNCA dispara en BTC
  2015-2026. En el cache ETH-USDT el maximo es **24.07%** (2020-03-12 10:00) — a 0.9pp del
  umbral. Las anclas v5 NO estan afectadas.
- **Riesgo latente:** en otro dataset (ETH con otro gap-fill, otro activo, otro rango) el filtro
  podria SALTARSE en silencio la barra de decision de un crash dentro del backtest — un cambio de
  comportamiento que nunca se midio aislado (rompe el protocolo).
- **Accion recomendada:** limitar el rechazo por salto a clientes live/paper (como ya hace la rama
  "OHLCV insuficiente"), o como minimo loggear + contar disparos en backtest.
- **RESUELTO (2026-07-02, fixes ruta live post-freeze):** `_market_data_ok` es no-op con
  `BacktestClient`. Ancla 2015-26 realistic re-verificada identica tras el cambio.

### B1n. [BAJO] `fill_next_open=True`: compra con gap alcista puede rechazarse en silencio

- **Donde:** `core/backtest.py` (`_fill_market` + branch buy "Saldo insuficiente").
- **Que pasa:** el sizing se calcula contra el close de la barra de decision con buffer 0.35%;
  si el open siguiente gapea por encima del buffer, la orden se rechaza sin log visible y la
  medicion pierde ese rebalanceo. Ademas, en la ultima barra cae de vuelta al fill al close.
- **Por que BAJO:** `fill_next_open` es solo modo de MEDICION (default False, F10 no adoptado).
- **Accion:** si se vuelve a usar para medir, contar rechazos y reportarlos.

### B2n. [BAJO] `OKXClient.get_ohlcv` conserva la vela en curso (confirm flag descartado)

- **Donde:** `core/exchange.py` (paginacion F12) — se descarta la columna `confirm` de OKX sin
  filtrar velas no confirmadas (igual que el codigo anterior).
- **Por que BAJO:** los consumidores ya se protegen: Swing excluye el dia en curso
  (`daily_on_closed_only`), Pro Trend excluye el bloque 4H incompleto. Sin sesgo hoy.
- **Accion:** si se anade un consumidor nuevo de OHLCV live, recordar que la ultima fila puede
  ser una vela parcial (documentado aqui).

### B3n. [BAJO] Dos referencias "v4 congelado" difieren ~0.3% entre etapas de medicion

- Smoke CLI post-F1/F2: final $9.307M / CAGR +86.2%. Baseline tools F5/F8:
  $9.28M / +86.11%. Mismo warmup nominal (250d), misma config. Drift sin atribuir
  (probable diferencia menor de harness CLI vs tools).
- **Por que BAJO:** no afecta a las anclas v5, que se definen con UN solo harness
  (`tools/swing_v5_freeze_report.py`, mismo patron que el resto de tools). CAGR/DD coinciden
  al primer decimal en todas las mediciones.
- **Accion:** las anclas oficiales v5 son las del freeze report. No comparar finales absolutos
  entre harnesses distintos.

### B4n. [BAJO] `_compute_trade_pnl_acb` descarta ventas sin posicion sin contarlas

- **Donde:** `core/backtest.py` (`continue` en la rama sell con `qty_open <= 0`).
- **Por que BAJO:** solo aplicaria a cortos sinteticos (`allow_shorts`, irrelevante para Swing y
  para Pro Trend default). Si algun dia se auditan metricas con shorts, este metodo los ignora.

---

## VERIFICACION PUNTO POR PUNTO (protocolo /audit-backtest)

### 1. Lookahead — SIN HALLAZGOS NUEVOS ✅

- **F8 verificado correcto:** `resample_to_daily` etiqueta por INICIO de dia (resample "1D",
  label left) y el corte es estricto (`daily["dt"] < current_day`) → el dia parcial en curso
  queda SIEMPRE excluido de ema50d/ema200d/rsi/adx/pi_cycle con el flag True. La fecha de corte
  sale del open de la barra actual (conservador).
- `BacktestClient.get_ohlcv` entrega hasta la barra actual inclusive; la decision se toma al
  close de esa barra 1H (cerrada). Sin cambio vs v4.
- `_market_data_ok` usa `iloc[-2]` (barra anterior cerrada) vs ticker actual — no mira futuro.
- F10 `fill_next_open` usa el open de la barra siguiente SOLO para el fill (anti-lookahead por
  construccion); default False.
- Offsets de contexto externo (MVRV dia anterior, VIX/DXY/NDX sesion anterior, funding dia
  completo anterior): NO tocados por el diff — verificados intactos en `macro_context._lookup`
  y companeros.

### 2. Leakage — SIN HALLAZGOS ✅

- Warmup excluido de simulacion y benchmark (`bars[self._warmup]` como primer precio B&H;
  equity solo post-warmup). Sin shift negativo ni resample con label derecho en el diff.
- F4 (`set_phase_bounds`): defaults reproducen el comportamiento historico EXACTO; validacion
  `0 < post < peak < onset` y warning si se cambian. El riesgo es el estado global (M1), no leakage
  temporal.

### 3. Costes — SIN HALLAZGOS ✅

- Fee 0.1% en CADA fill: compra `cost = size*price + fee`; venta `proceeds = size*price - fee`.
- F1 (ACB) es contable puro: fee de compra capitalizada en el coste medio, fee de venta prorrateada
  si la cantidad se recorta. La equity NO cambia (verificado: mismas anclas con acb/legacy).
- F11: el B&H ahora paga fee+slippage de su unica compra — direccion JUSTA (endurece el benchmark
  de la misma forma que la estrategia paga sus fills).

### 4. Slippage — SIN HALLAZGOS ✅

- Aplicado por modo (0/5/15 bps) sobre el precio raw en `_fill_market`, sentido correcto
  (buy paga mas, sell recibe menos). Buffer 0.35% de los rebalanceos intacto.

### 5. Timezone — SIN HALLAZGOS ✅

- Todos los timestamps nuevos tz-aware UTC (`datetime.fromtimestamp(..., tz=timezone.utc)`,
  `pd.Timestamp(..., tz="UTC")`). `get_ohlcv` live devuelve ms int64 UTC identico al backtest.
  Sin conversiones a local en rutas de calculo.

### 6. Gaps — SIN HALLAZGOS ✅

- Dataset canonico 102931 velas: continuo, cero huecos >24h (validado en adopcion 2026-07-02).
- La paginacion live (F12) deduplica por timestamp y ordena ascendente; no fabrica velas.

### 7. Overfitting — SIN HALLAZGOS ✅ (con nota)

- v5 NO anade ningun threshold fitted: `daily_on_closed_only=True` se adopto POR HIGIENE
  costando -0.27pp CAGR (direccion opuesta a overfitting). F9/F10 se midieron y NO se adoptaron
  pese a ser neutros — protocolo respetado.
- `max_price_jump_pct=0.25` es un threshold nuevo con justificacion estructural (control
  operativo live anti flash-crash/fat-finger), inerte en los datasets actuales — pero ver M2.
- La ventana 2015-2026 sigue CERRADA (regla invariante #5); F5/F6/F7 solo MIDIERON.

---

## RESOLUCION DE HALLAZGOS DE LA AUDITORIA V4

| Hallazgo v4 | Fix | Estado verificado en codigo |
|---|---|---|
| B1/B2 calendario halving hardcoded/fragil | F4 + F5 | ✅ parametrizado con defaults exactos; fragilidad medida y documentada (shift -60d: +72.86% CAGR; +60d: DD -66.08%). No resuelto de raiz — es fragilidad del EDGE, no del codigo; queda como riesgo conocido |
| B3 P&L por trade roto (pairing sin igualar qty) | F1 | ✅ ACB con fees prorrateados; equity identica; PF sigue NO-ancla |
| B4 paridad live rota (get_ohlcv 300, sin ruta start) | F12/F13/F14/F15 | ✅ paginado int64 + ruta start + RiskManager + controles; PENDIENTE cierre real: 24h runtime y paridad 30d (requieren paper) |
| B5 data snooping de proceso | 0.2 | ✅ regla invariante #5 en SESSION.md; ventana cerrada |
| C1 fill al close de la decision | F10 | ✅ medido (+86.08% vs +86.11%): optimismo despreciable; default sin cambio |
| C2 indicadores diarios con dia parcial | F8 | ✅ ADOPTADO (el delta v5); verificado sin off-by-one |
| C3 riesgo USDT | F16 | ✅ stress -5/-10% medido; riesgo aceptado con sizing/custodia prudente |
| C4 underwater infrarreportado | F2 | ✅ `underwater_days` peak→recovery (922d) junto a peak→trough (260d) |
| C6 cadencia dependiente del offset | F9 | ✅ medido, NO adoptado (no mejora); sensibilidad documentada |
| C7 EMA200D truncada sin documentar | F11 | ✅ comentario en config |
| C8 sizing sin base formal | F7+F17 | ✅ bootstrap x1000 (DD p95 -68.31% / p99 -74.34%) + marcos de sizing en SESSION.md |
| C9 B&H sin costes | F11 | ✅ fee+slip de entrada aplicados al benchmark |

---

## ANCLAS v5 (re-verificadas en el freeze, `tools/swing_v5_freeze_report.py`)

| Ventana | Costes | Final | CAGR | Max DD | Rebalances | btc_vs_bnh |
|---|---|---:|---:|---:|---:|---:|
| BTC 2015-2026 | realistic | $9,137,545.81 | +85.84% | -52.73% | 70 | 0.8171 |
| BTC 2018-2026 | realistic | $219,763.03 | +47.14% | -53.72% | 53 | 0.8432 |
| BTC 2015-2026 | conservative | $8,897,454.17 | +85.40% | -52.88% | 70 | 0.7961 |

Secundarias (2015-26 realistic / 2018-26 realistic / 2015-26 conservative):
Calmar 1.63 / 0.88 / 1.61 · Sharpe 1.38 / 1.00 / 1.37 · Sortino 1.57 / 1.18 / 1.57 ·
underwater max 922d en las tres (mismo periodo 2021-2024). PF ACB 78.5 / 67.4 / 75.1 —
contable, NO ancla.

Re-verificacion ejecutada 2026-07-02 al cierre del freeze (exit 0, coincidencia exacta con los
valores del freeze de la sesion anterior). Coste del fix anti-lookahead (F8) vs v4 congelado:
-0.27pp CAGR / -0.02pp DD. Rollback exacto a v4: `--config '{"daily_on_closed_only": false}'`.

---

## CONCLUSION

v5 queda congelado como default. Los hallazgos M1/M2 son riesgo LATENTE (inertes en los datos
actuales) y no bloquean el freeze; quedan anotados para resolverse si se reabre codigo. El
siguiente hito NO es mas backtest: validacion forward/paper (cierra F13/F15/F19). La fragilidad
del calendario de halving (B2) sigue siendo el riesgo estructural #1 del edge y solo el forward
puede des-riesgarla.
