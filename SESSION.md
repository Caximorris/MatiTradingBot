# SESSION.md — Estado del proyecto y referencia detallada

Complemento de CLAUDE.md. Actualizar al cerrar cada sesion.
**Ultima actualizacion: 2026-06-26 (quinta sesion)**

---

## ESTADO ACTUAL

**Version en codigo: Pro Trend v12** con 5 lookahead fixes y framework de validacion completo.
**Resultado honesto con costes realistas: +480.5% CAGR +24.7% vs B&H +549.7% CAGR +26.4%**
La ventaja real de Pro Trend NO es el retorno absoluto — es el riesgo: 35% tiempo en mercado, evita crashes del -70%.

---

## PROXIMOS PASOS (orden estricto — no cambiar parametros antes de completarlos)

### 1. Baselines correcto
```bash
python main.py baselines --from 2018-01-01 --to 2026-01-01 --costs realistic
```
El baseline "sin externos" anterior estaba roto. Fix aplicado: `disable_external_filters=True` en ProTrendConfig.
Pregunta: sin MVRV/VIX/DXY/funding, ¿mejora o empeora? Si mejora → los filtros externos danian la estrategia.

### 2. ETH backtest (anti-overfitting)
```bash
python main.py backtest --strategy pro --symbol ETH-USDT --from 2020-01-01 --to 2026-01-01 --costs realistic
```
Pi Cycle Top auto-desactivado para no-BTC en main.py.

### 3. Sensitivity analysis (implementar + correr)
Barrer sin cambiar nada — el objetivo es MEDIR fragilidad, no optimizar:
- `entry_score_min`: 8 / **9** / 10
- `adx_min_entry`: 10.0 / **15.0** / 20.0
- `trailing_stop_pct_bull`: 0.24 / **0.28** / 0.32
- `cooldown_atr_stop_days`: 15 / **30** / 45

### 4. Journal MAE/MFE/R-multiplo
Añadir a `reporting/trade_journal.py` y `strategies/base_strategy.py`:
- MAE: maximo adverso desde entrada hasta cierre
- MFE: maximo favorable desde entrada hasta cierre
- R-multiplo: PnL / (entry_price × ATR_stop_dist)

### 5. Informe final + paper trading
Paper trading MANDATORIO min 6 meses con sizing 50% antes de capital real:
```bash
python main.py start --strategy pro --symbol BTC-USDT
# --config '{"size_ultra": 0.45, "size_high": 0.40, "size_mid": 0.30}'
```

---

## RESULTADOS DE BACKTEST

| Estrategia | Periodo | Balance | P&L | Trades | PF | CAGR |
|------------|---------|---------|-----|--------|----|------|
| **Pro Trend v12 (ideal)** | 2018-2026 | $71,412 | +614% | 11 | 5.81 | +28.0% |
| Pro Trend v12 (realistic) | 2018-2026 | $58,050 | +480.5% | 12 | 3.64 | +24.7% |
| BTC Buy & Hold (realistic) | 2018-2026 | ~$64,971 | +549.7% | — | — | +26.4% |
| Pro Trend v11 | 2018-2026 | $74,124 | +641% | 11 | 5.61 | +28.6% |
| Adaptive Trend (realistic) | 2018-2026 | ~$48,090 | +380.9% | 20 | 2.91 | +21.8% |
| Scalp Momentum v4 | 2022-2026 | $9,640 | -3.6% | 351 | 0.93 | -0.8% |

### Distribucion profit v12 (costes ideal)
- T4 Q1-2021: +$16,442 | T5 Q2-2021: +$17,111 | T9 Q3-2024: +$21,323
- T10 Q1-2025: +$9,989 (out-of-sample) | T11 Q4-2025: +$7,850 (out-of-sample)
- 5 perdedores: ~-$12,767
- **ADVERTENCIA: T4+T5+T9 = 89% del profit**

### Baselines comparativos (realistic, 2018-2026)
| Estrategia | P&L | CAGR | PF |
|---|---|---|---|
| Pro Trend v12 completo | +480.5% | +24.7% | 3.64 |
| Pro Trend sin externos (*pendiente re-correr*) | ? | ? | ? |
| Pro Trend score_min=1 (gates only) | +443.3% | +23.7% | 3.74 |
| Pro Trend sizing fijo 50% | +229.7% | +16.2% | 4.08 |
| **Buy & Hold BTC** | **+549.7%** | **+26.4%** | — |

Conclusiones: scoring aporta poco (gates solos = 92%); sizing adaptativo si aporta (~2x vs fijo 50%).

### Walk-Forward (realistic, 4 ventanas — 1 invalida)
| Ventana TEST | CAGR | PF | Trades | vs B&H |
|---|---|---|---|---|
| 2022-2023 | +10.7% | — (1W) | 1 | Gana (B&H ~-10%) |
| 2024-2026 | +12.2% | 4.22 | 4 | Pierde (B&H ~+150%) |
| 2021-2022 | +6.3% | 1.24 | 4 | Gana (B&H ~-43%) |
| 2023-2025 | +43.3% | 8.56 | 2 | Solo 2 trades |
| TRAIN 18-21 | — | — | 0 | INVALIDA (fallo descarga OKX) |

---

## PRO TREND v12 — REFERENCIA COMPLETA

### 13 gates de entrada long (en orden)
VIX < 35 → score >= 9 → ventaja > 2 → weekly_trend not False → h4_bullish not False
→ MVRV < 2.5 (long_reduce_risk=False) → funding < 0.0005 → DXY no headwind
→ NASDAQ no risk-off → Pi Cycle Top inactivo → RSI ok (0=off) → ATR ok (0=off)
→ ADX >= 15.0 → MACD alcista en D o 4H
Gates como variables `_g_*` en run() para diagnostico en logs.

### ProTrendConfig — valores actuales v12
```python
entry_score_min         = 9      # todos los ganadores historicos tuvieron score >= 9
adx_min_entry           = 15.0   # bloquea mercados sin tendencia
entry_score_gap         = 2
exit_score_floor        = 3
size_ultra              = 0.90   # post_halving/bull_peak con score >= 8
size_high               = 0.80   # fuera de bull phase con score >= 8
size_mid                = 0.60   # score < 8
size_short_cap          = 0.15
trailing_stop_pct       = 0.22   # bear/accumulation
trailing_stop_pct_bull  = 0.28   # post_halving/bull_peak
cooldown_bear_days      = 30
cooldown_trailing_bull_days = 7
cooldown_atr_stop_days  = 30
max_loss_pct            = 20.0
atr_stop_mult           = 3.0
allow_shorts            = False
macd_exit_enabled       = False
lookback_hours          = 15000  # 625 dias para SMA350D (Pi Cycle Top)
pi_cycle_enabled        = True   # auto False para no-BTC en main.py
disable_external_filters = False # True solo para ablation tests
```

### Sizing adaptativo
- `size_ultra` (90%): score >= 8 en post_halving/bull_peak
- `size_high` (80%): score >= 8 fuera de bull phase
- `size_mid` (60%): score < 8
- Ajustes: bear_onset x0.75 | MVRV euphoria cap 20% | VIX>22 cap size_mid | VIX>35 bloqueo | shorts cap 15%

### Cache de indicadores
- `_daily_cache`: {"date": "YYYY-MM-DD", "ind": {...}}
- `_weekly_cache`: {"week": "YYYY-Www", "ind": {...}}
- `_4h_cache`: {"key": "YYYY-MM-DD-N", "ind": {...}} donde N = hora // 4

### Cooldown (date-based, no barras)
- ATR stop: 30 dias (`cooldown_atr_stop_days`)
- Hard stop: 15 dias
- Trailing stop bear/accum: 30 dias (`cooldown_bear_days`)
- Trailing stop bull: 7 dias (`cooldown_trailing_bull_days`)

### Sistema de puntuacion long (max ~14 pts)
+2 tendencia semanal alcista | +1 EMA50D>EMA200D | +1 precio>EMA200D | +1 slope EMA50D+
+1 swing uptrend | +2 MACD crossover (+1 si solo positivo) | +2 RSI div alcista
+1 OBV slope+ | +1 ADX>20 con golden cross | +1 soporte S/R o VAL
+1 FVG alcista | +1 vol spike alcista | +1 BB dip/squeeze breakout

### Shorts sinteticos (allow_shorts=True)
No ordenes reales OKX. Margen USDT reservado via `adjust_balance()`. Registrados via `_log_short_trade()`.
CRITICO: `OrderResult` requiere `size=qty, limit_price=None`.

---

## MACRO CONTEXT (macro_context.py)

Fuente: CoinMetrics Community API (gratuito, sin API key).
Metricas: `CapMVRVCur` + `PriceUSD`. `PriceRealizedUSD` NO disponible en tier gratuito.
Realized Price = PriceUSD / CapMVRVCur.
URL: usar `%2C` para separar metricas (comma URL-encoded).

MVRV umbrales: deep_bear<1.0 | recovery<2.0 | bull 2.0-2.5 | late_bull 2.5-3.5 | euphoria>3.5
- `long_reduce_risk=True` si MVRV >= 2.5
- Maximo historico backtests: ~2.96 (Q2 2021) — con umbral 2.5 activa en T5 y T9

Halvings BTC: 28-Nov-2012, 9-Jul-2016, 11-May-2020, 20-Abr-2024, ~15-Mar-2028 (estimado)
Fases: post_halving(0-180d) | bull_peak(180-540d) | bear_onset(540-900d) | accumulation(>900d)

Modo degradado: `short_allowed=True, long_reduce_risk=False` si falla CoinMetrics.

---

## MARKET CONTEXT (market_context.py)

Fuente: Yahoo Finance API (urllib, User-Agent obligatorio o da 403).
Tickers: `^DXY`, `^NDX`, `^VIX`

Senales:
- `dxy_headwind`: DXY subio > 1.5% en 10 dias → bloquea longs
- `risk_off`: NASDAQ bajo > 5% en 10 dias → bloquea longs
- `vix_elevated`: VIX > 22 → cap sizing al 60%
- `vix_extreme`: VIX > 35 → bloqueo total de entrada

Modo degradado silencioso si falla Yahoo Finance.

---

## FUNDING CONTEXT (funding_context.py)

OKX liquida 3 veces/dia (00:00, 08:00, 16:00 UTC).
`get_funding_rate_at(dt)`: siempre delta >= 1 (dia anterior completo) — lookahead fix.
Umbral: > 0.0005 bloquea longs; < -0.0005 bloquea shorts.

---

## INDICADORES (strategies/indicators.py — UNICO modulo activo)

`ema`, `sma`, `macd`, `atr`, `rsi`, `adx`, `obv`, `ema_slope`, `bb_bands`,
`swing_structure`, `sr_levels`, `fvg_zones`, `rsi_divergence`,
`resample_to_1h`, `resample_to_4h`, `resample_to_daily`, `resample_to_weekly`,
`volume_profile` → (poc, vah, val)

RENDIMIENTO: resample_to_daily/weekly son O(n²) — mitigado con _daily_cache/_weekly_cache.

---

## ADAPTIVE TREND (adaptive_trend.py)

Estado: FUNCIONAL. Resultado 2018-2026 realistic: +380.9%, 20 trades, PF 2.91, CAGR +21.8%.
Solo longs. Logica: regimen (EMA50D/200D/ADX) → entrada MACD+RSI+vol → salida bear/MACD/RSI/ATR.

---

## SCALP MOMENTUM (scalp_momentum.py)

Estado: EN EVALUACION. Correr en 1H (no 15m).
Resultado v4 (15m): -3.6%, PF 0.75, 351 trades — no rentable.
```bash
python main.py backtest --strategy scalp --from 2022-01-01 --to 2026-06-01 --timeframe 1H
```

---

## OVERFITTING — THRESHOLDS EN RIESGO

Ajustados sobre solo 11 trades historicos — no se puede saber si son robustos:
- `entry_score_min=9` — 5 perdedores tuvieron score<9 en v10
- `adx_min_entry=15.0` — muy especifico para tan pocos trades
- `trailing_stop_pct_bull=0.28` — calibrado sobre crash Evergrande T5 2021
- `cooldown_atr_stop_days=30` — calibrado sobre brecha T8/T9 2024
- `atr_stop_mult=3.0` — subido porque 2.5 disparo T5 prematuramente

Walk-forward: 3/3 ventanas validas positivas → logica no es memorizacion pura.
Pero: 1-4 trades por ventana, base estadistica muy pequena.

Protocolo antes de capital real:
1. Baselines correcto → 2. ETH backtest → 3. Sensitivity analysis → 4. Paper trading 6 meses

Senales de alarma en live:
- Mas de 3 entries en un mes (historico: 1-2 por año)
- Trade pierde > 25% (hard stop es 20%)
- Score en entrada < 9
- Cooldown ignorado (revisar `_cooldown_until` en DB)

---

## EVOLUCION PRO TREND

| Version | Cambio clave | Impacto |
|---------|-------------|---------|
| v8 | macd_exit=False | +$8k vs v7 |
| v9 | trailing_bull=0.28, cooldown_atr=30d, sizing_bull=75% | +$6.7k |
| v10 | MVRV_FAIR=3.0, atr_mult=3.0, score_min=7 | |
| v10+VIX+Funding | VIX layers, funding historico | +$17.7k |
| v11 | score_min=9, sizes 90/80/60%, sin penalizacion acumulacion | +$19.3k |
| v12 | adx_min=15, gate MACD cross-TF, bear_onset×0.75 | ideal +614%, realistic +480% |

---

## BUGS RESUELTOS (no re-investigar)

1. `_log_short_trade()` sin `size`/`limit_price` → añadidos al OrderResult
2. Weekly flip oscillation (miles de trades): fix `weekly_trend is not False` en long_ok
3. Sin cooldown tras weekly flip: fix `_set_cooldown()` date-based
4. `h1["close"]` no existia en dict fallback: fix añadir `"close": last_close`
5. UnicodeEncodeError Windows cp1252: sustituidos caracteres Unicode por ASCII

---

## LO QUE NO HA FUNCIONADO

- Backtests anuales independientes — posiciones desaparecen, contexto se pierde
- Price reference con `daily["close"]` en lugar de `h1["close"]` — artificial
- RSI bearish div +2 pts en short score — demasiado ruido en bull markets
- Shorts activados en Pro Trend 2018-2026 — pierde en correcciones de bull market
- MACD cross exit en ScalpMomentum — cortaba ganadores antes del TP

---

## DATOS EXTERNOS

| Fuente | Datos | Autenticacion |
|--------|-------|---------------|
| CoinMetrics Community API | MVRV (CapMVRVCur + PriceUSD) | Sin API key |
| Yahoo Finance | DXY, NDX, VIX | Sin API key, User-Agent obligatorio |
| OKX REST API | OHLCV historico, funding rate | Sin auth para publicos |
| Binance REST API | OHLCV fallback si OKX da 0 barras | Sin auth |

Multi-activo: MVRV disponible para BTC y ETH. SOL/BNB: degradacion silenciosa.
Pi Cycle Top solo BTC. Halvings solo BTC.

---

## JOURNAL (reporting/trade_journal.py)

`write_journal(journal, strategy_name, symbol, timeframe, from_date, to_date, cost_mode, config_overrides)`
Archivo: `backtests/journal_{estrategia}_{simbolo}_{timeframe}_{ts}.json`
Meta incluye `cost_mode` y `config_overrides` para identificar la sesion y config exacta.
