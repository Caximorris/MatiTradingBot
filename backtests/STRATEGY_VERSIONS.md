# Registro de versiones de estrategias

Documento para NO repetir cambios que ya probamos. Cada version tiene su config exacta,
el resultado backtest y el veredicto. Antes de cambiar cualquier parametro, consultar aqui.

---

## BTC Buy & Hold (referencia)
- 2018-2026: +549% (de $10k a ~$65k)
- Siempre el benchmark a superar o al menos proteger

---

## REGLAS DE VALIDACION PRO TREND

Estas reglas aplican antes de tocar parametros o promover cambios a default:

1. **Lookahead bias cero.**
   Usar solo velas cerradas y datos externos disponibles antes del tick: dia anterior para MVRV,
   sesion anterior para DXY/NDX/VIX, dia completo anterior para funding, semana/4H actual excluidas
   si estan incompletas.

2. **BTC 2015-2026 es la muestra principal.**
   Cubre 3 ciclos bull y da mas trades. 2018-2026 sigue siendo benchmark reciente contra B&H,
   pero no basta para aprobar cambios.

3. **Overfitting control.**
   No aprobar cambios que solo eliminan 1 trade perdedor o mejoran una ventana corta. Cada cambio
   debe testearse aislado, con costes realistic, y preferiblemente contra ETH/walk-forward si altera
   comportamiento de entrada/salida.

4. **v13 es baseline/rollback.**
   Mantener documentada y reproducible la configuracion v13: `partial_exit_pct=150.0`,
   `partial_exit_size=0.33`, `entry_score_min=9`, `adx_min_entry=15.0`,
   `trailing_stop_pct_bull=0.28`, `cooldown_atr_stop_days=30`,
   `macd_exit_enabled=False`, `allow_shorts=False`. No borrar journals v13.

---

## PRO TREND

### v4 — Baseline (ultima version antes de la sesion 2026-06-24)
**Periodo:** 2018-01-01 → 2026-01-01
**Resultado:** +258% ($35,819) | 30 trades | 40% WR | PF 2.86

**Config clave:**
- lookback_hours = 8760 (365 dias)
- MVRV_FAIR = 3.0 (nunca se activo — max MVRV historico fue 2.96)
- Sin Pi Cycle Top
- warmup = 380 dias
- allow_shorts = False
- trailing_stop_pct = 0.22
- entry_score_min = 6
- cooldown_bear_days = 30

**Exits:** trailing_stop=6 (66.7% WR) | macd_exit=19 (42.1% WR) | atr_stop=3 (0%) | bear_confirmed=2 (0%)

**Analisis critico:**
- 4 trades MACD exit con PnL > 10% que se podrian haber aguantado: Oct23-Ene24 (+42%), Ene-Mar24 (+52%), Oct24-Ene25 (+45%), Jun-Ago25 (+13%)
- Q2-Q3 2024 cluster de perdidas: 4 trades consecutivos = -5,965 USDT
- El trade Jul2020-Ene2021 generó +12,737 (el 49% del PnL total en UN trade)
- Weakly EMA50 con solo 52 semanas de datos (muy ruidoso)

---

### v5 — MVRV_FAIR=2.5 + Pi Cycle Top + lookback=15000 (2026-06-24)
**Periodo:** 2018-01-01 → 2026-01-01
**Resultado:** +123% ($22,339) | 23 trades | 30.4% WR | PF 2.22

**Cambios respecto a v4:**
- MVRV_FAIR: 3.0 → 2.5 (ahora se activa a MVRV 2.5+)
- Pi Cycle Top anadido (EMA111D > 2xEMA350D)
- lookback_hours: 8760 → 15000 (625 dias, EMA350D correcta)
- warmup: 380 → 625 dias

**Por que empeoro:**
1. lookback=15000 cambio EMA50W (weekly) de ~2 puntos utiles a 39 — diferente senales de entrada
   → Bloqueo la entrada de Apr 2019 (+4,338) que en v4 era una senal noisy/ruidosa
   → Redujo sizing del trade Jul2020 de $5,333 a $3,924 por menor balance acumulado
2. MVRV_FAIR=2.5 bloqueo Feb2021 (+1,940), Apr2021 (-503), May2021 (-974) = net +463 bloqueado
   → El bloqueo fue correcto pero el trade Feb2021 +1,940 es una ganancia perida
3. Nuevas perdidas en 2024 no existentes en v4: -1,309, -1,795, -608 (distintas fechas de entrada)
4. Pi Cycle Top nunca se activo (no habia posicion abierta cuando disparo en May2021)

**Analisis critico:**
- MVRV SÍ funciona: max historico fue 2.96 (Q2 2021), el umbral 2.5 bloquea la fase tardana correctamente
- El lookback largo (15000) es MAS CORRECTO aunque cambia el comportamiento
- El mismo problema del MACD exit existe: 4 trades >10% con weekly bullish cortados prematuramente
- Q2 2024 cluster sigue existiendo (ambas versiones sufren esto)

**Lo que NO debemos revertir:**
- lookback=15000 (es mas correcto aunque genere resultados distintos)
- MVRV_FAIR=2.5 (bloquea correctamente la euforia — el trade bloqueado Feb2021 MVRV=2.87 vale +1,940 pero no justifica arriesgar entrar en MVRV 2.5+)
- Pi Cycle Top (correcto, solo que aun no ha disparado en un trade abierto)
- warmup=625 (necesario para EMA350D)

---

### v6 — MACD exit mejorado + consecutive loss cooldown (2026-06-24) [IMPLEMENTADO]
**Cambios respecto a v5:**
- MACD exit se OMITE si profit > 10% Y weekly_trend_up = True (deja correr al trailing stop)
- Consecutive loss cooldown: despues de 2 perdidas consecutivas → 15 dias cooldown extra
  (estado: _consecutive_losses, _consec_cooldown_until en _load_state defaults)
  (metodo _track_loss_streak llamado desde _close_long)
  (check en run() combinado con _cooldown_until principal)

**Razon:**
- 4 trades en ambas versiones: MACD exit con >10% ganancia + weekly bullish = dejar correr
- Q2 2024: 4 trades consecutivos perdiendo. Con cooldown tras 2 perdidas, los trades 3 y 4 se bloquean
- Ahorro estimado Q2 2024: +1,905 USDT (v5) / +2,717 USDT (v4) en trades 3 y 4 bloqueados

**PENDIENTE:** correr backtest y actualizar resultados aqui

---

### v7 — Auditoria: SMA Pi Cycle + RSI filter + ATR ext + gates diagnostico (2026-06-24) [IMPLEMENTADO]
**Cambios respecto a v6:**
- Pi Cycle Top: EMA111D + EMA350D → SMA111D + SMA350D (el indicador estandar usa SMA, no EMA)
- `pi_cycle_action` configurable: "exit_full" | "exit_half" | "block_entries" (defecto: exit_full)
- `entry_rsi_max` configurable (defecto: 0.0 = desactivado). Ej: --config '{"entry_rsi_max": 72}'
- `entry_max_ema20_atr` configurable (defecto: 0.0 = desactivado). Ej: --config '{"entry_max_ema20_atr": 2.5}'
- Gates desglosados como variables individuales (_g_score, _g_gap, _g_weekly, etc.) para diagnostico
- Log detallado cuando entrada bloqueada y score cerca del umbral (ls >= entry_score_min - 1)
  → Log muestra exactamente qué gate bloqueo y el valor que lo causó

**Cambios en backtest.py:**
- Sharpe ratio CORREGIDO: ahora usa bars_per_year segun timeframe (1H=8760, antes hardcoded 252)
  → TODOS los Sharpe historicos estaban mal calculados
- Nuevas metricas en BacktestResult y summary_rows: CAGR, Sortino, Expectancy,
  Avg Win, Avg Loss, Max racha perdedoras, Tiempo en mercado
- BacktestEngine acepta timeframe= para calcular correctamente las metricas
- Nota de funding: log explícito que funding_rate = 0.0 en backtest (no se valida)
- main.py: pasa timeframe= a BacktestEngine

**Metricas NO activadas por defecto (entry_rsi_max=0, entry_max_ema20_atr=0):**
Requieren backtest A/B antes de activar por defecto. Para probar:
  --config '{"entry_rsi_max": 72.0}'
  --config '{"entry_max_ema20_atr": 2.5}'

**Resultados v7 (2018-01-01 → 2026-01-01):**
- Balance: $21,733 (+117%) | 18 trades | 33.3% WR | PF 2.94
- Sharpe: 0.43 | Sortino: 0.56 | CAGR: 10.2%/año | Tiempo en mercado: 29.7%
- Avg Win: +$2,965 | Avg Loss: -$505 | Expectancy: +$651/trade
- Exits: trailing_stop=3 (100% WR, +$13,002) | macd_exit=9 (44% WR, +$1,311)
         atr_stop=3 (0% WR, -$2,072) | bear_confirmed=2 (0% WR, -$1,947)
- DXY nunca bloqueo ninguna entrada (dxy=False en todos los trades)
- 5 trades menos que v5 (18 vs 23) por consecutive loss cooldown (v6)
- 2023 Jan-Jun perdido: score diario ls=2-3 (estructura bajista), no hay bug
- Trade Oct23-May24 (RSI=74 en apertura): bloquearia con entry_rsi_max=72 — CUIDADO

---

### v8 — macd_exit_enabled=False como DEFAULT (2026-06-24) [IMPLEMENTADO]
**Cambios respecto a v7:**
- `macd_exit_enabled: bool = False` — ahora es el DEFAULT (antes True)
- La estrategia sale solo por: trailing_stop, atr_stop, bear_confirmed, score_floor
- Activar MACD exit: --config '{"macd_exit_enabled": true}'

**Resultados v8 (2018-01-01 → 2026-01-01):**
- Balance: $30,310 (+203%) | 11 trades | 45.5% WR | PF 3.73
- CAGR: 14.9%/año | Sharpe: 0.62 | Sortino: 0.81 | Tiempo en mercado: 31.0%
- Avg Win: +$5,551 | Avg Loss: -$1,241 | Expectancy: +$1,846/trade
- Max DD: -31.15% | Max racha perdedoras: 2
- Exits: trailing_stop=6 (67% WR, +$22,220) | bear_confirmed=1 (100%, +$2,849)
         atr_stop=4 (0% WR, -$4,638)

**Vs v7 (+117% con MACD exit ON):**
- +$8,577 de mejora (+39% mas capital)
- Trades 18→11: el MACD exit fragmentaba tendencias grandes en trades pequenos
- Caso emblematico: May2020→Jan2021 era 3 trades (-$399, -$490, +$7,207 = +$6,318 neto)
  Sin MACD exit: UN trade de +$13,476 via trailing stop (las correcciones intermedias
  del 10-15% que el MACD interpretaba como "death cross" eran solo ruido de la tendencia)
- El trailing stop ahora ES la estrategia: 67% WR, genera +$22,220 de un total de +$25,069

**Trade list v8:**
- 2019-06-17→06-27  ls=9  RSI=66  trailing_stop  +$720
- 2019-08-02→08-29  ls=6  RSI=52  trailing_stop  -$266  (pico insuficiente)
- 2020-02-03→02-28  ls=12 RSI=65  atr_stop       -$353
- 2020-05-18→21-01-11  ls=9 RSI=62 trailing_stop +$13,476 ← mayo2020 to enero2021 sin interrupciones
- 2021-08-16→09-21  ls=10 RSI=68  trailing_stop  -$2,474 (run-up luego crash Q3 2021)
- 2023-07-11→08-17  ls=8  RSI=59  atr_stop       -$609
- 2023-10-23→24-05-01 ls=10 RSI=74 trailing_stop +$7,148
- 2024-05-31→06-24  ls=9  RSI=55  atr_stop       -$1,724
- 2024-07-22→08-02  ls=10 RSI=68  atr_stop       -$1,951
- 2024-10-18→25-02-26 ls=9 RSI=67 trailing_stop  +$3,616
- 2025-05-06→10-21  ls=10 RSI=61  bear_confirmed +$2,849

**Riesgo identificado:**
- 1 trade (+$13,476) representa el 44% del capital final — concentracion extrema
- Los ATR stops son ahora mas grandes (-$1,724, -$1,951) sin MACD exit que los frene antes
- Max DD -31.15% (vs desconocido en v7 pero probablemente menor)

**Siguiente paso:** ablation de pi_cycle_action y entry_rsi_max

---

---

## SCALP MOMENTUM

### v1 — 15m, config original (2026-06-24)
**Periodo:** 2022-01-01 → 2026-06-01
**Resultado:** -36% (-$3,603) | 5,431 trades | 37.4% WR | PF 0.75

**Config:**
- timeframe: 15m
- atr_stop_mult = 1.5, atr_tp_mult = 3.0
- allow_shorts = True
- entry_score_min = 7, entry_score_gap = 3

**Exits:** atr_stop=2101 (0% WR) | macd_cross=2069 (38.1% WR) | take_profit=602 (100% WR)
  | rsi_oversold=329 (98.8% WR!) | rsi_overbought=330 (96.4% WR!)

**Problema principal:** atr_stop 2101 trades con 0% WR en 15m. Demasiado ruido.
  El macd_cross exit (2069 trades) cortaba ganadores.
  RSI exits tenian WR casi perfecto — se eliminaron al pasar a 1H y fue un error.

**Lo que NO debemos repetir:**
- macd_cross como exit en scalp (se elimino con razon — cortaba ganadores)
- atr_stop_mult=1.5 en 15m (demasiado estrecho para el ruido de BTC en 15m)

---

### v2 — 1H, allow_shorts=True, atr_stop=1.5, atr_tp=3.0 (2026-06-24)
**Periodo:** 2022-01-01 → 2026-06-01
**Resultado:** -13% (-$1,115) | 824 trades | 34.7% WR | PF 0.88

**Cambios respecto a v1:**
- timeframe: 15m → 1H
- Eliminado: macd_cross exit, rsi_overbought/oversold exit
- allow_shorts = True (mantenido)
- atr_stop_mult = 1.5, atr_tp_mult = 3.0 (igual que v1)

**Exits:** atr_stop=487 (0% WR) | take_profit=282 (100% WR) | score_floor=52 (7.7% WR) | hard_stop=3

**Analisis critico:**
- Score en apertura identico para ganadores y perdedores (7.7 vs 7.8) — el score no predice
- ATR stop 1.5xATR = 1.19% precio promedio = puro ruido en 1H BTC
- Shorts pierden 4.4x mas que longs: longs -207 USDT, shorts -907 USDT
- Trades <8h: -1,736 USDT (26% WR) vs >8h: +621 USDT (39% WR)
- Ratio actual winner/loser: 1.61x. Necesitamos 1.88x para breakeven a 34.7% WR

**Lo que NO debemos repetir:**
- atr_stop_mult=1.5 en 1H (sigue siendo estrecho, 487 stops con 0% WR)
- allow_shorts=True en scalp (shorts son un lastre claro)
- Eliminar RSI exits fue un error (v1 tenia 98%+ WR con RSI exits)

---

### v3 — 1H, allow_shorts=False, atr_stop=2.5, atr_tp=5.0 (2026-06-24)
**Periodo:** 2022-01-01 → 2026-06-01
**Resultado:** +6.4% (+$641) | 261 trades | 38.7% WR | PF 1.15

**Cambios respecto a v2:**
- allow_shorts: True → False (-907 USDT de perdida eliminada)
- atr_stop_mult: 1.5 → 2.5 (stop mas ancho, menos ruido)
- atr_tp_mult: 3.0 → 5.0 (TP mas lejos, mayor ganancia por trade)

**Exits:** take_profit=83 (100% WR, avg +56 USDT) | score_floor=82 (22% WR) | atr_stop=96 (0% WR)

**Mejora clara:** primer PF > 1. Direccion correcta pero aun marginal.

**Analisis critico:**
- ATR stop: 96 trades, avg -33 USDT, avg holding 19.8h (sigue siendo el lastre)
- Score_floor: 82 trades, 22% WR — cortando posiciones que podrian recuperarse
  (avg hold 62.8h — son salidas tardias, no anticipadas)
- TP: 83 trades, 100% WR, avg +56.41, avg 35.5h — el exit mas valioso
- Score en apertura IDENTICO para winners y losers (7.7 ambos) — confirmado: el score no predice
- RSI exits del v1 (98%+ WR) siguen ausentes

**Lo que hay que mejorar:**
- Anadir RSI exit: close long si RSI > 75 Y posicion en ganancia
- atr_stop_mult: 2.5 → 3.0 (reducir mas los stops de ruido)
- exit_score_floor: 2 → 1 (solo salir si la senal es verdaderamente mala)

---

### v4 — RSI exit + atr_stop=3.0 + exit_score_floor=1 (2026-06-24) [IMPLEMENTADO]
**Cambios respecto a v3:**
- rsi_exit: close long si RSI > 75 Y price > entry, tras min_hold_bars (8h)
- atr_stop_mult: 2.5 → 3.0
- exit_score_floor: 2 → 1

**Razon:**
- v1 tenia RSI exits con 98%+ WR — recuperar ese mecanismo de salida
- atr_stop_mult=3.0 da mas margen contra ruido sin llegar a ser un "soft stop" inutilizable
- Score_floor a 1 evita salidas por consolidaciones temporales (score baja a 2 brevemente)

**Resultados v4 (2022-01-01 → 2026-06-01, 1H):**
- Balance: $9,640 (-3.60%) | 351 trades | 52.4% WR | PF 0.93
- CAGR: -0.8%/año | Sharpe: -1.45 | Sortino: -1.99 | Tiempo en mercado: 24.9%
- Avg Win: +$28 | Avg Loss: -$33 | Expectancy: -$1.03/trade
- Exits: rsi_exit=155 (99% WR, +$4,004) | take_profit=28 (100% WR, +$1,427)
         atr_stop=100 (0% WR, -$3,811) | score_floor=67 (3% WR, -$1,356)
- Pre-fees la estrategia sería ~breakeven (+$161 neto, fees ~$526 para 351 trades)

**Diagnostico critico:**
- Por año: 2022=-$244, 2023=+$366, 2024=+$310, 2025=-$218 — correlacion con trending/choppy
- En mercados en rango (ADX bajo), el precio cruza EMA50D frecuentemente → señales falsas
- Score en apertura IDENTICO para winners y losers (7.7 ambos) — el score no predice resultado
- RSI exit es el mejor exit (99% WR) pero corta demasiado pronto (avg $25.8 vs TP avg $51)
- ATR stop 0% WR: correcto (red de seguridad), pero hay 100 hits = mercado lateral
- La raiz del problema: falta filtro de régimen (trending vs lateral)

---

### v5 — ADX + Weekly + Macro + Market + Trailing Stop (2026-06-24) [IMPLEMENTADO]
**Cambios respecto a v4:**
- `daily_adx_min = 20`: no operar cuando ADX diario < 20 (mercado lateral)
- `weekly_trend_filter = True`: bloquea longs si EMA10W < EMA20W (macro bajista)
  - lookback_bars aumentado 3000 → 4320 (180 dias para EMA20W)
  - nuevo metodo _build_weekly_context() con cache por semana ISO
- `use_macro_filter = True`: importa get_macro_signal() — bloquea longs si MVRV >= 2.5
  (mismo umbral que Pro Trend, datos ya cargados en memoria por _run_backtest)
- `use_market_filter = True`: importa get_market_context() — bloquea longs en rally DXY
  o crash NASDAQ (mismos filtros que Pro Trend, datos ya en memoria)
- `trailing_stop_pct = 0.07 / trailing_min_profit = 0.03`:
  trailing stop activo tras min_hold_bars si ganancia > 3%
  cierra si el precio cae 7% desde el pico post-entrada

**Razon:**
- ADX: 2022 y 2025 son mercados laterales — sin tendencia, el scalp pierde
- Weekly: misma logica que Pro Trend, bloquea entradas contra la macro
- Macro (MVRV): en euforia (MVRV > 2.5) el momentum de scalp es poco fiable
- Market (DXY/NASDAQ): los mismos adversos que Pro Trend aplican al scalp
- Trailing: captura movimientos fuertes antes de que revierten
  (RSI exit cortaba demasiado pronto a $25 promedio vs TP a $51)

**Ablation: para aislar cada filtro:**
```bash
# v5 completo
python3 main.py backtest --strategy scalp --from 2022-01-01 --to 2026-06-01 --timeframe 1H
# solo ADX (reproduce v4 original de otro modo)
python3 main.py backtest --strategy scalp --from 2022-01-01 --to 2026-06-01 --timeframe 1H --config '{"weekly_trend_filter":false,"use_macro_filter":false,"use_market_filter":false,"trailing_stop_pct":0.0}'
# sin trailing (para ver impacto del trailing solo)
python3 main.py backtest --strategy scalp --from 2022-01-01 --to 2026-06-01 --timeframe 1H --config '{"trailing_stop_pct":0.0}'
```

**PENDIENTE:** correr backtest y actualizar resultados aqui

---

## ADAPTIVE TREND

### v1 — Baseline (antes de sesion 2026-06-24)
**Periodo:** 2018-2024
**Resultado:** +409% ($50,900) | — trades | — WR | — PF

**Config:** EMA50D > EMA200D + ADX > 20 + MACD crossover + RSI 40-70 + Vol > 1.2x
  Salida: bear_confirmed | MACD cross + precio < EMA50D | RSI > 80 (recorte 50%) | ATR stop 2.5x

**Nota:** Supera a Pro Trend aunque usa logica mas simple. La clave es el sizing (80%) y
  dejar correr las posiciones. No tocar hasta que Pro Trend supere este resultado.

---

## SWING ALLOCATOR

Concepto: mantiene siempre BTC (min 30%), ajusta 30-100% segun regimen (EMA50D/200D+ADX) y
fase de halving. Rebalancea cuando |target-actual| > threshold. Nunca sale del todo.

### v0 — regime + halving deltas ±0.10 (2026-06-30)
**Config:** `use_regime=True, use_halving=True`, resto False. `delta_post_halving=+0.10, delta_bear_onset=-0.10`.
**Resultado:** 2015-26 +70.5% CAGR, PF 3.38, 64 trades | 2018-26 +34.8% CAGR | WF 4/4 ✅

### v1 — halving deltas ±0.20 (2026-06-30) [DEFAULT hasta sesion 13]
**Config:** igual que v0 pero `delta_post_halving=+0.20, delta_bear_onset=-0.20`.
**Resultado (dataset canonico 96906 velas, realistic):**
- 2015-26: +78.4% CAGR, PF 4.33, 65 trades, Max DD -57.60%, Q4 2025 **-$129,784**
- 2018-26: +36.7% CAGR, PF 3.77, Max DD -58.11%
- WF 4/4 ✅ | ETH +56.4% CAGR | conservative +69.8% CAGR
**Problema:** ping-pong Q4 2025 — `regime_bull`(+0.20) vs `halving_bear_onset`(-0.20) con BTC lateral
$103-112k → EMA50D/200D cruzaba cada 3-5d → 5 rebalanceos perdedores.

### v2 — regime_off_on_bear_onset (2026-07-01, sesion 13) [DEFAULT ACTUAL]
**Config:** igual que v1 + **`regime_off_on_bear_onset=True`**.
**Cambio:** cuando `bear_onset` esta activo, suprime SOLO la rama `regime_bull` (mantiene `regime_bear`).
Estructural: `bear_onset` = fase de distribucion post-halving; perseguir breakouts alcistas ahi es
sistematicamente una trampa (2018, 2021-22, 2025). Suprimir solo la compra alinea con la tesis del halving.
**Resultado (mismo dataset, realistic):**
- 2015-26: **+80.6% CAGR, Max DD -55.23%**, 58 trades, Q4 2025 **+$290,232** (vs v1 78.4%/-57.60%/-$130k)
- 2018-26: **+41.5% CAGR, Max DD -53.42%** (vs v1 36.7%/-58.11%)
- WF 4/4 TEST positivo (+16.1/+36.4/+13.2/+82.8%), >= v1 en las 4 ventanas ✅
- ETH: identico a v1 (sin halvings, el flag nunca dispara) ✅
**Veredicto:** ADOPTADO. Unico candidato que mejora AMBAS anclas (CAGR y Max DD) en las dos ventanas
+ pasa WF. Reversible: `--config '{"regime_off_on_bear_onset": false}'` vuelve a v1.
**Version DESCARTADA (no repetir):** suprimir TODO el regime en bear_onset (no solo bull) — rompio 2022
al desactivar la defensa `regime_bear` (mantuvo 40% BTC en el bear -77% en vez de 30%): Q1 2023 -$274k,
Max DD -59.02%. La supresion debe ser SOLO de la rama bull.

**Pendiente:** reduccion de Max DD (cap `max_btc_pct` en bull_peak / vol-targeting). Diagnostico:
el DD viene de estar 90-100% BTC en techos de ciclo (mayo 2021: 100% BTC, de-risk tardio a -36%),
no de los bears (donde ya esta en floor 30%).

---

## LECCIONES APRENDIDAS (NO repetir estos experimentos)

1. **Backtest anual con reset de balance**: descartado — posiciones abiertas desaparecen
2. **allow_shorts en Pro Trend**: descartado — en bull markets shortea en correcciones y pierde
3. **macd_cross exit en Scalp**: descartado — cortaba ganadores sistematicamente
4. **atr_stop_mult=1.5 en cualquier timeframe de BTC**: demasiado estrecho, 0% WR garantizado
5. **allow_shorts en ScalpMomentum**: descartado — longs -207 USDT vs shorts -907 USDT (4.4x peor)
6. **entry_score como predictor de calidad en Scalp**: confirmado que NO funciona
   (7.7 score promedio identico para winners y losers en todas las versiones)
7. **MVRV_FAIR = 3.0**: nunca se activaba (max historico 2.96) — cambiado a 2.5
8. **lookback_hours = 8760 con EMA350D**: insuficiente para convergencia (solo 15 dias utiles post-convergencia)
   → usar 15000 siempre para Pro Trend

---

### v9 — Phase-aware trailing + ATR cooldown + bull sizing (2026-06-24)
**Cambios respecto a v8:**

1. **trailing_stop_pct_bull = 0.28** (en post_halving/bull_peak, vs 0.22 para todo):
   - BTC corrige 20-28% durante bull markets sin romper estructura
   - El 22% expulsaba en correcciones validas (Trade 5 Aug-Sep 2021: -$2,474)
   - Con 28%: Trade 5 en Bull Peak, $52k peak → trail en $37,440 → Sept crash $40k NO dispara
   - BTC sube a $67k en Nov 2021 → trade sigue vivo, trade en zona profitable
   - Cooldown tras trailing en bull phase: 7 dias (era 30) para re-entrada rapida en ciclo alcista

2. **cooldown_atr_stop_days = 30** (era 5 via cooldown_bars):
   - Trade 8 (ATR stop Jun-24) + Trade 9 (entry Jul-22 = 28 dias despues): Trade 9 BLOQUEADO
   - Trade 9 = -$1,951 evitado. Patron: re-entrada en mismo nivel de precio tras ATR stop

3. **Sizing: score>=8 en post_halving/bull_peak → 75%** (era solo score>=10):
   - Trade 4 (score=9, post_halving): 60%→75%, +$3,369 adicionales
   - Trade 10 (score=9, bull_peak): 60%→75%, +$904 adicionales
   - Trade 8 (score=9, post_halving, ATR stop): amplia la perdida (+$431), pero bloqueado Trade 9

**Mejora esperada vs v8 (+203%):**
- Trade 5 de -$2,474 a ~break-even o leve profit: +$2,500-$3,000
- Trade 9 bloqueado: +$1,951
- Sizing: +$3,842
- Total estimado: +$8,000-9,000 → ~$38,000-$39,000 (+280-290%)

**Resultados v9 (2018-01-01 → 2026-01-01):**
- Balance: $37,079 (+270.8%) | 9 trades | 55.6% WR | PF 7.82
- Trades: T8 bloqueado (cooldown_atr_stop=30d, 28d < 30d). T9 no existio.
- Confirmado: trailing_bull=0.28 no disparo en correcciones intermedias
- Vs v8 (+$8.7k mejora)

**Siguiente:** MVRV_FAIR=3.0 (max historico fue 2.96, el 2.5 nunca se activaba en bull)

---

### v10 — MVRV_FAIR=3.0 + atr_mult=3.0 + VIX + Funding historico (2026-06-25)
**Cambios respecto a v9:**
1. **MVRV_FAIR: 2.5 → 3.0** — el max historico fue 2.96 (Q2 2021). Con 2.5, el umbral
   nunca se activaba en la practica. Con 3.0: MVRV 2.96 (Q2 2021) y 2.53 (Q2 2024)
   ahora bloquean entradas → correcto.
2. **atr_stop_mult: 2.5 → 3.0** — Trade 5 (corrección Evergrande 2021) disparaba con 2.5x
3. **VIX cargado** desde Yahoo Finance (^VIX) junto a DXY/NDX en market_context.py:
   - `vix_elevated` (VIX > 22): cap sizing a size_mid (60%)
   - `vix_extreme` (VIX > 35): hard block de entrada (panico sistemico)
   - El umbral dinamico de score (VIX > 22 → +2) fue ELIMINADO tras analisis:
     T4 (May 2020, score=9, VIX~28) hubiese sido bloqueado — es el trade mas grande.
4. **Funding rate historico** via funding_context.py descargando historico real OKX
   (antes BacktestClient devolvía siempre 0.0)
5. **MVRV_FAIR revertido de 2.5 a 3.0** — el max historico fue 2.96, con 2.5 T9 acumulacion
   (Oct23-Jul24, MVRV=1.8) ahora entra con sizing mayor

**Resultados v10 (2018-01-01 → 2026-01-01):**
- Balance: $54,832 (+448.3%) | 11 trades | 54.5% WR | PF 7.054
- T9 (acumulacion Oct23): entra con 60% por MVRV<2.5 vs ahora 80% → +$17.7k adicionales
- Vs v9: +$17.7k — cambio mas grande de toda la evolucion hasta este punto

---

### v11 — Sizing agresivo 90/80/60% + score_min=9 + sin penalizacion acumulacion (2026-06-25)
**Cambios respecto a v10:**
1. **entry_score_min: 7 → 9** — analisis de v10 journal: todos los ganadores tuvieron score>=9
   en el momento de entrada; los 5 perdedores tuvieron score 7-8. Score 9 = confirmacion real.
   CUIDADO: el threshold de entrada cambia la FECHA de entrada (no es que bloquee el trade —
   la estrategia entra en la primera barra que alcanza score=9, que puede ser distinta a la v10).
2. **Sizing: 90%/80%/60%** (era 75%/60%/40%): usuario tiene cartera diversificada,
   acepta sizing agresivo en la estrategia de BTC
3. **Penalizacion acumulacion ELIMINADA**: en fase acumulacion (MVRV bajo), la señal de
   entrada es de alta conviccion — no tiene sentido penalizar. Solo bear_onset sigue con ×0.75.

**VIX con score dinamico ELIMINADO (error corregido):**
El codigo anterior aumentaba entry_score_min en +2 cuando VIX > 22. Esto hubiese bloqueado
T4 (May 2020, score=9, VIX~28), el mayor winner con +$17,608. Se elimino el dinamismo:
VIX ahora solo afecta SIZING (cap 60%) y tiene hard block en VIX>35.

**Resultados v11 (2018-01-01 → 2026-01-01):**
- Balance: $74,124 (+641.2%) | 11 trades | 54.5% WR | PF 5.61
- **CAGR: +28.6%/año — SUPERA BTC B&H (+24.5%/año)**
- T4 (May2020→Jan2021): +$17,608 (+201%) — post_halving, size_ultra=90%
- T5 (Jan→Apr2021): +$18,340 (+74%) — bull_peak, Pi Cycle Top exit
- T9 (Oct2023→Jul2024): +$22,160 (+82%) — acumulacion pre-ETF, sin penalizacion
- 91% del profit viene de estos 3 trades

**Por que el PF cayo de 7.05 a 5.61:**
- Sizing mayor (80-90% vs 40-60%) → las perdidas son mayores en dolares aunque los % son iguales
- T6 (Mar2021 atr_stop): -$5,051 (v11) vs -$3,634 (v10) — mismo % pero mayor capital invertido
- Es la contrapartida del sizing agresivo: las ganancias suben pero las perdidas tambien

**Trade list v11:**
- T1  2019-06-19→06-28  ls=9  atr_stop       -$521
- T2  2019-08-06→08-30  ls=9  trailing_stop  -$466
- T3  2020-02-05→02-28  ls=9  atr_stop       -$1,238
- T4  2020-05-18→21-01-13  ls=9  trailing_stop  +$17,608 ← MEGA WINNER
- T5  2021-01-03→04-15  ls=9  pi_cycle_top   +$18,340 ← Pi Cycle exit perfecto
- T6  2021-03-08→03-25  ls=9  atr_stop       -$5,051
- T7  2023-07-14→08-17  ls=9  atr_stop       -$1,453
- T8  2023-10-25→24-05-01  ls=10  trailing_stop  +$7,654
- T9  2024-08-07→25-01-20  ls=9  trailing_stop  +$22,160 ← MEGA WINNER
- T10 2025-02-13→03-28  ls=9  bear_confirmed -$2,700
- T11 2025-05-08→      ls=9  [abierto al corte 2026-01-01]

---

### v12 — ADX gate + MACD cross-TF gate + bear_onset ×0.75 (2026-06-25) [IMPLEMENTADO, SIN BACKTEST]
**Cambios respecto a v11:**
1. **adx_min_entry = 15.0**: bloquea entradas cuando ADX < 15 (mercado sin tendencia definida)
   Objetivo: evitar entrar en consolidaciones donde el scoring puede ser alto por inercia
2. **Gate MACD cross-timeframe**: al menos uno de (daily.macd_above OR h4.h4_macd_above)
   Objetivo: confirmar momentum alcista en al menos un TF de mayor escala
3. **Penalizacion bear_onset ×0.75 RESTAURADA** (se mantiene solo para bear_onset):
   En inicio de mercado bajista, la conviccion debe ser mayor para justificar el tamaño

**PENDIENTE:** correr backtest
```bash
python main.py backtest --strategy pro --from 2018-01-01 --to 2026-01-01
```

**Estimacion:** si ADX y MACD no bloquean ninguno de los 6 ganadores, resultado ~$80-85k

---

### v13 — Partial exit default + auditoria de medicion (2026-06-30)

**Estado:** implementado en codigo con `partial_exit_pct=150.0` y `partial_exit_size=0.33`.

**Resultado documentado 2018-2026 realistic:**
- partial_exit=150: balance $62,184 | +521.84% | 12 trades | PF journal true 4.64
- referencia sin partial exit: balance $58,051 | +480.51% | 12 trades | PF ~3.64
- BTC B&H: ~$64,971 | +549.7%

**Resultado documentado 2015-2026 realistic:**
- Journal `20260629_155853` valida 3 ciclos bull, pero fue generado sin partial exit.
- Pendiente correr 2015-2026 con default v13 real (`partial_exit_pct=150.0`).

**Auditoria importante:**
- Los journals con partial exit no deben compararse solo por `statistics.total_pnl_usdt`.
  `close.pnl_usdt` mide el cierre final de la posicion restante y puede omitir PnL ya realizado
  en la venta parcial. Para comparar usar balance final o `balance_after - balance_before`.
- El journal `20260629_153049` con `partial_exit_pct=200.0` muestra balance final $64,158
  (+541.59%), superior al 150% en retorno bruto, aunque con PF journal true menor (3.69).
  Revalidar antes de concluir.

**Veredicto v13:**
- Mantener 150% como default operativo hasta rerun limpio.
- No cambiar parametros por intuicion: primero arreglar medicion del journal y re-testear 150 vs 200.
- La ventaja real sigue siendo riesgo/tiempo en mercado; en retorno bruto queda cerca de B&H.

---

## PRO TREND - BACKLOG v14 / TEST QUEUE

Orden recomendado:

1. **P0 Medicion sin cambiar trades**
   - Journal: calcular `true_pnl_usdt` por balance e incluir PF real cuando hay partial exits. IMPLEMENTADO 2026-06-30.
   - Journal: incluir `meta.resolved_config`, `meta.backtest`, sizing real/planificado, gates de entrada,
     contexto macro/mercado/funding y giveback desde MFE. IMPLEMENTADO 2026-06-30.
   - Journal: registrar partial exits como eventos o sub-operaciones. PENDIENTE opcional.
   - Backtest log: actualizar mensaje de funding, porque ya usa `funding_context.get_funding_rate_at()`. IMPLEMENTADO 2026-06-30.

2. **P1 Bugfixes candidatos**
   - MACD 4H gate: `h4.get("h4_macd_above", True)` parece clave equivocada; el contexto 4H devuelve
     `macd_above`. Probar fix aislado.
   - VIX elevated cap: el sizing log usa `vix_elevated`, pero `_open_long()` recalcula sizing sin ese
     parametro. IMPLEMENTADO 2026-06-30 solo en Pro Trend; pendiente backtest aislado. No toca
     Swing Allocator ni `market_context.py`.

3. **P2 Experimentos de mejora**
   - Profit-lock o break-even tras MFE +10/+15/+20%.
   - Trailing bull grid 0.28/0.30/0.32/0.34 en 2018-2026 y 2015-2026.
   - ADX como modificador de sizing en vez de gate duro.
   - MVRV late-bull como de-risk/profit-lock, no solo bloqueo.
   - BTC core + Pro Trend overlay para competir contra B&H en retorno bruto.

**Criterio de default:** un cambio debe mejorar 2018-2026 y 2015-2026 con costes realistic, sin
empeorar de forma material MaxDD/PF. Si solo elimina un trade perdedor de muestra pequeña, tratar
como overfitting hasta validar en ventana larga, ETH o walk-forward.

---

## LECCIONES APRENDIDAS (NO repetir estos experimentos)

1. **Backtest anual con reset de balance**: descartado — posiciones abiertas desaparecen
2. **allow_shorts en Pro Trend**: descartado — en bull markets shortea en correcciones y pierde
3. **macd_cross exit en Scalp**: descartado — cortaba ganadores sistematicamente
4. **atr_stop_mult=1.5 en cualquier timeframe de BTC**: demasiado estrecho, 0% WR garantizado
5. **allow_shorts en ScalpMomentum**: descartado — longs -207 USDT vs shorts -907 USDT (4.4x peor)
6. **entry_score como predictor de calidad en Scalp**: confirmado que NO funciona
   (7.7 score promedio identico para winners y losers en todas las versiones)
7. **MVRV_FAIR = 2.5**: nunca se activaba correctamente (max historico 2.96 en Q2 2021)
   → usar 3.0 que captura correctamente la euforia historica de BTC
8. **lookback_hours = 8760 con EMA350D**: insuficiente — usar 15000 siempre para Pro Trend
9. **VIX con score dinamico**: cuando VIX>22 aumentar entry_score_min en +2 bloquearia T4
   (May 2020, score=9, VIX~28) que es el mayor winner historico. VIX solo afecta SIZING.
10. **Ajustar thresholds sobre trades especificos**: ADX=15.0, MACD gate, cooldown=30d,
    trailing=0.28 fueron elegidos conociendo los trades historicos. Con solo 11 trades,
    el riesgo de overfitting es real. MANDATORIO: paper trading antes de capital real.
