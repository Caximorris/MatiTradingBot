# MatiTradingBot — CLAUDE.md

Guia completa para Claude Code. Leer SIEMPRE antes de tocar cualquier archivo.

---

## 1. CONTEXTO DEL PROYECTO

Bot de trading automatizado para OKX. Python 3.12+. Residencia fiscal Espana (IRPF).
El usuario opera desde Windows 10. Shell primario: PowerShell. Bash tambien disponible.

**Objetivo principal:** estrategias rentables que superen o protejan frente a BTC Buy & Hold,
con backtesting continuo multi-año, informes fiscales IRPF, y despliegue live en OKX.

**Directorio raiz:** `C:\Users\Matias\Documents\Mati\matiproyects\MatiTradingBot\okx_trader\`

---

## 2. STACK TECNOLOGICO

| Paquete | Uso |
|---------|-----|
| python-okx | SDK oficial OKX (REST + WebSocket) |
| SQLAlchemy 2.x + SQLite | Persistencia (WAL mode, in-memory para backtests) |
| pandas 2.x + numpy | Calculo de indicadores |
| loguru | Logging con rotacion diaria |
| typer + rich | CLI y tablas de resultados |
| APScheduler | Scheduler para ejecucion periodica live |
| tenacity | Retry automatico en llamadas a OKX |
| aiohttp | Webhooks async |
| python-telegram-bot | Alertas Telegram |
| openpyxl | Exportacion Excel informes fiscales |
| urllib (stdlib) | Fetch datos externos (CoinMetrics MVRV, Yahoo Finance) — sin requests |

**No usar `requests`** — no esta en requirements.txt. Usar `urllib.request` para HTTP sincrono
o `aiohttp` para async.

---

## 3. ESTRUCTURA DE ARCHIVOS

```
okx_trader/
├── main.py                         # CLI typer — todos los comandos
├── requirements.txt
├── config/
│   └── settings.py                 # Settings frozen dataclass, fail-fast en startup
├── core/
│   ├── database.py                 # Trade/Position/BotState + CRUD helpers, WAL SQLite
│   ├── exchange.py                 # OKXClient (paper+live), OrderResult dataclass, RateLimiter
│   ├── backtest.py                 # BacktestClient + BacktestEngine + fetch_historical_bars
│   └── risk_manager.py             # can_open_position, calculate_position_size, daily loss check
├── data/
│   ├── market_data.py              # OHLCVBar dataclass, fetch helpers
│   └── indicators.py               # Modulo antiguo (no usar directamente)
├── strategies/
│   ├── base_strategy.py            # Clase abstracta: log_trade, check_risk, abstract run()
│   │                               # Incluye journal helpers: _journal_open(), _journal_close()
│   ├── indicators.py               # UNICO modulo de indicadores activo (ver seccion 6)
│   ├── adaptive_trend.py           # Estrategia 1: regimen bull/bear/range, solo longs
│   ├── pro_trend.py                # Estrategia 2: multi-timeframe, longs (shorts opcionales)
│   ├── scalp_momentum.py           # Estrategia 3: day trading 15m con contexto 1H/4H/D
│   ├── macro_context.py            # MVRV + halving cycle (singleton global)
│   └── market_context.py           # DXY + NASDAQ-100 (singleton global, Yahoo Finance)
├── execution/
│   ├── order_manager.py            # Gestion de ordenes
│   └── position_tracker.py        # Tracking de posiciones abiertas
├── reporting/
│   ├── trade_logger.py             # TradeLogger.log() + from_order_result()
│   ├── trade_journal.py            # write_journal() — JSON detallado por backtest
│   ├── fiscal_report.py            # IRPF FIFO, tramos 2026, Excel+JSON
│   └── dashboard.py                # Dashboard rich
└── backtests/                      # JSON journals generados automaticamente por backtest
```

**Archivos eliminados** (ya no existen — no buscarlos):
- `strategies/mean_reversion.py` — eliminado
- `strategies/signal_follower.py` — eliminado

---

## 4. COMANDOS CLI DISPONIBLES

Todos se ejecutan desde `okx_trader/` con `python main.py <comando>`.

```bash
# Backtest continuo de una estrategia
python main.py backtest --strategy pro --from 2018-01-01 --to 2024-12-31
python main.py backtest --strategy scalp --from 2022-01-01 --to 2026-01-01 --timeframe 15m

# Comparar estrategias (descarga barras UNA SOLA VEZ para todas)
python main.py compare --strategies "adaptive,pro" --from 2018 --to 2024

# Monte Carlo: N ventanas aleatorias de M meses dentro del historico BTC
python main.py random-backtest --strategy pro --windows 10 --months 24

# Live trading
python main.py start --strategy adaptive --symbol BTC-USDT
python main.py stop
python main.py status

# Informes
python main.py trades
python main.py report
python main.py dashboard
```

**IMPORTANTE:** No ejecutar automaticamente estos comandos tras implementar cambios.
El usuario los corre el mismo en su propia consola para ver el progreso en tiempo real.
Mostrar el comando exacto y dejar que el usuario lo lance.

---

## 5. ARQUITECTURA DE BACKTESTING

### Diseno clave
`BacktestClient` imita la interfaz de `OKXClient` al 100% — las estrategias se ejecutan
SIN ningun cambio de codigo. El motor inyecta barra a barra y la estrategia cree que
esta en live.

### Flujo de BacktestEngine.run()
```
factory(client, session) -> strategy     # DB in-memory SQLite
for i in range(warmup, n):
    client.advance(i)                    # avanza la barra actual
    strategy.run()                       # la estrategia opera normalmente
    equity_curve.append((ts, balance))  # timestamp + saldo total
    if on_tick: on_tick(done, total)    # callback barra de progreso
```

### Warmup
- Adaptive Trend: 240 dias de warmup antes del from_dt (para EMA200D)
- Pro Trend: 380 dias de warmup antes del from_dt (para EMA200D + EMA50W)
- Scalp Momentum: 25 dias de warmup (para EMA20D diaria)

### REGLA CRITICA: Backtests CONTINUOS, nunca anuales
Nunca reiniciar el balance a 1 de enero. Las posiciones sobreviven el cambio de año.
El historial de equity_curve tiene timestamps reales para calcular retornos anuales
a posteriori. Los trimestres son solo para DISPLAY, no para logica de estrategia.

### Barra de progreso (Rich)
`_run_backtest()` en main.py usa `rich.progress.Progress` con:
- Fase 1: descarga (on_page callback)
- Fase 2: simulacion (on_tick callback cada 500 barras)
- `transient=True` → la barra desaparece al terminar, deja solo la tabla final

### Equity curve
`BacktestResult.equity_curve: list[tuple[datetime, Decimal]]` — timestamps UTC reales.
Se usa para calcular retornos anuales con `_annual_returns_from_curve()` en main.py.

### Trade Journal automatico
Al finalizar cada backtest, si la estrategia tiene trades en `_journal`, se escribe
un archivo JSON detallado en `backtests/journal_{estrategia}_{simbolo}_{timeframe}_{ts}.json`.
Contiene indicadores completos en apertura y cierre, scores, contexto macro/mercado.

---

## 6. MODULO DE INDICADORES (strategies/indicators.py)

ESTE ES EL UNICO modulo de indicadores activo. `data/indicators.py` es el antiguo — ignorar.

Funciones disponibles:
- `ema(series, period)` → pd.Series
- `sma(series, period)` → pd.Series
- `macd(close, fast, slow, signal)` → (macd_line, signal_line, histogram)
- `atr(high, low, close, period)` → pd.Series
- `rsi(close, period)` → pd.Series
- `adx(high, low, close, period)` → pd.Series
- `obv(close, volume)` → pd.Series
- `ema_slope(series, period)` → pd.Series (diferencia entre ultimos N valores)
- `bb_bands(close, period, std)` → (upper, mid, lower, width, pct_b)
- `swing_structure(high, low, lookback)` → "uptrend" | "downtrend" | "neutral"
- `sr_levels(high, low, lookback)` → (supports: list[float], resistances: list[float])
- `fvg_zones(o, h, l, c, lookback)` → (bull_fvgs, bear_fvgs) — Fair Value Gaps
- `rsi_divergence(close, rsi, lookback)` → "bullish" | "bearish" | None
- `resample_to_1h(df)` → DataFrame con col "dt" (para ScalpMomentum desde 15m)
- `resample_to_4h(df)` → DataFrame con col "dt"
- `resample_to_daily(df)` → DataFrame con col "dt"
- `resample_to_weekly(df)` → DataFrame con col "dt"
- `volume_profile(close, volume, high, low, lookback=100, n_buckets=40, value_area_pct=0.70)` → (poc, vah, val)
  - POC = Point of Control (bucket con mas volumen)
  - VAH / VAL = Value Area High / Low (70% del volumen desde POC)
  - Usado en scoring: VAL sustituye/complementa S/R clasico para longs, VAH para shorts

**PROBLEMA DE RENDIMIENTO CONOCIDO:** `resample_to_daily()` y `resample_to_weekly()`
se llaman en cada barra horaria — O(n^2). La estrategia ya cachea el resultado por dia/semana
(`_daily_cache` y `_weekly_cache` en el estado) para mitigar esto, pero el resampling
inicial sigue siendo costoso. Pendiente optimizacion.

---

## 7. ESTRATEGIA: ADAPTIVE TREND (adaptive_trend.py)

**Estado: FUNCIONAL. Mejor resultado actual.**

### Logica en 3 capas
1. **Regimen** (barras diarias, 210 dias de ventana):
   - bull  = EMA50D > EMA200D AND precio > EMA200D AND ADX > 20
   - bear  = EMA50D < EMA200D OR precio < EMA200D
   - range = bull estructural pero ADX < 20 (mercado lateral)

2. **Entrada** (solo en regimen bull):
   - MACD(12,26,9) diario cruza al alza
   - RSI(14) entre 40 y 70
   - Volumen del dia > 1.2x media 20 dias
   - Tamano: 80% del saldo disponible

3. **Salida:**
   - Regimen cambia a bear → salida inmediata
   - MACD cruza a la baja Y precio < EMA50D
   - RSI > 80 → reduce posicion al 50%
   - ATR stop: precio cae > 2.5x ATR(14) desde entrada

### Resultados backtest 2018-2024 (continuo)
- Balance final: ~$50,900 (+409%, 5.09x)
- Solo longs, no opera shorts
- Evita los crashes de 2018 (-80%) y 2022 (-75%) gracias al regimen bear

---

## 8. ESTRATEGIA: PRO TREND (pro_trend.py)

**Estado: FUNCIONAL — version actual en codigo: v9 (SIN BACKTEST).**
**Ultima actualizacion sesion 3: trailing_stop_pct_bull=0.28, cooldown_atr_stop=30d, sizing bull 75%.**

### Diseno
Multi-timeframe con sistema de puntuacion (0-14 pts por lado). Shorts opcionales
(desactivados por defecto: `allow_shorts=False`).

### Timeframes y indicadores usados
| Timeframe | Indicadores |
|-----------|-------------|
| Semanal | EMA20W, EMA50W, slope → `weekly_trend_up` bool |
| Diario | EMA20D, EMA50D, EMA200D, SMA111D, SMA350D, slopes, MACD, RSI, ATR, ADX, OBV, BB, Swing, S/R, RSI_div, Volume Profile, Pi Cycle Top |
| 4H | EMA20/50 4H, MACD 4H, swing 4H → `trend_bullish` / `trend_bearish` bool |
| Horario (1H) | FVG zones, BB squeeze/breakout, vol spike, precio actual |
| Macro (externo) | MVRV ratio, Realized Price, halving cycle phase |
| Mercado global | DXY (dollar index), NASDAQ-100 (risk-off filter) |

### Sistema de puntuacion (por lado, max ~14 pts)
**Long score:**
- +2 tendencia semanal alcista (EMA20W > EMA50W + slope > 0)
- +1 EMA50D > EMA200D
- +1 precio > EMA200D
- +1 slope EMA50D positivo
- +1 swing = uptrend
- +2 MACD crossover alcista (o +1 si solo positivo)
- +2 RSI divergencia alcista
- +1 OBV slope positivo
- +1 ADX > 20 con EMA50D > EMA200D
- +1 precio cerca de soporte (S/R clasico o VAL Volume Profile)
- +1 FVG alcista cercano
- +1 vol spike alcista
- +1 BB dip en tendencia alcista o squeeze breakout up

**Short score** (mirror, con ajustes):
- RSI divergencia bajista: solo +1 (reducido — en bull markets hay divs bajistas constantemente)
- +1 EMA200D slope negativo (confirma tendencia bajista estructural)

### Condiciones de entrada
```
long_ok = (
    ls >= 6                              # umbral longs (bajado de 7 — entra antes)
    AND ls > ss + 2                      # ventaja sobre shorts
    AND weekly_trend is not False        # no entrar long en tendencia semanal bajista
    AND h4["trend_bullish"] is not False # 4H alineado con long
    AND NOT macro["long_reduce_risk"]    # no entrar si MVRV >= 2.5 (late_bull/euphoria)
    AND funding < 0.0005                 # funding < 0.05%
    AND NOT market["dxy_headwind"]       # DXY no en rallye (adverso para BTC)
    AND NOT market["risk_off"]           # NASDAQ no en correccion severa
    AND NOT daily["pi_cycle_top"]        # SMA111D no > 2xSMA350D (señal de techo)
)
short_ok = (
    cfg.allow_shorts                     # DESACTIVADO por defecto — activar con config
    AND ss >= 9                          # umbral mas alto para shorts
    AND ss > ls + 2
    AND weekly_trend is not True
    AND ema_bear                         # EMA200D declinando + precio < EMA200D
    AND macro["short_allowed"]           # MVRV >= 2.0 Y halving phase no es bull
    AND above_realized                   # precio > Realized Price * 1.1
    AND h4["trend_bearish"] is not False # 4H alineado con short
    AND funding > -0.0005
)
```

### Condiciones de salida (por orden de prioridad)
1. **Trailing stop** (22% desde el pico desde entrada) + cooldown extendido (30 dias)
2. **Hard stop** si perdida > 20% desde entrada + cooldown 15 dias
3. **ATR stop** (precio cruza ATR×2.5 desde entrada) + cooldown normal (5 dias)
4. **Pi Cycle Top** (SMA111D > 2×SMA350D) + accion configurable (exit_full/exit_half/block_entries)
5. **Bear confirmado**: weekly bajista Y precio < EMA200D + cooldown extendido (30 dias)
6. MACD death cross + precio < EMA20D — **DESACTIVADO POR DEFECTO** (`macd_exit_enabled=False`)
   Backtest demostro que el MACD exit fragmentaba tendencias grandes. v8 sin MACD: +203% vs +117%.
   Activar con --config '{"macd_exit_enabled": true}'.
7. Score cae por debajo de exit_score_floor (3)
8. Recorte parcial 50%: RSI div bajista + RSI > 85 + ganancia > 40%

### Cooldown
El cooldown es DATE-BASED (`_cooldown_until: "YYYY-MM-DD"`), no de barras.
- Salida normal (ATR stop): 5 dias
- Hard stop: 15 dias
- Trailing stop o bear_confirmed: 30 dias (`cooldown_bear_days`)

### Sizing adaptativo
```python
# Por fase del ciclo × score:
size_ultra = 0.75   # score >= 10 en fase bull_peak / post_halving
size_high  = 0.60   # score >= 8
size_mid   = 0.40   # score 6-7

# Ajustes:
# MVRV euphoria: cap en 20%
# Fase bear_onset/accumulation: base × 0.65
# Shorts: cap fijo 15%
```

### ProTrendConfig — parametros clave (v9)
```python
entry_score_min         = 6      # umbral minimo para longs (bajado de 7)
entry_score_min_short   = 9      # umbral para shorts
entry_score_gap         = 2      # ventaja minima sobre score opuesto
exit_score_floor        = 3
size_ultra              = 0.75   # 75%: score>=8 en post_halving/bull_peak (v9: era solo score>=10)
size_high               = 0.60   # 60%: score>=8 fuera de bull phase
size_mid                = 0.40   # 40%: score 6-7
size_short_cap          = 0.15   # cap para shorts
trailing_stop_pct       = 0.22   # trailing en bear/accumulation o fase desconocida
trailing_stop_pct_bull  = 0.28   # [v9] trailing en post_halving/bull_peak (mas amplio)
cooldown_bars           = 5      # ya NO se usa para ATR stop (ver cooldown_atr_stop_days)
cooldown_bear_days      = 30     # cooldown tras bear_confirmed; trailing en bear/accumulation
cooldown_trailing_bull_days = 7  # [v9] cooldown tras trailing stop en bull phase (era 30)
cooldown_atr_stop_days  = 30     # [v9] cooldown tras ATR stop (era 5 via cooldown_bars)
max_loss_pct            = 20.0   # hard stop al -20%
atr_stop_mult           = 2.5    # ATR × 2.5
allow_shorts            = False  # shorts DESACTIVADOS por defecto
macd_exit_enabled       = False  # DESACTIVADO — fragmentaba tendencias grandes
partial_exit_pct        = 0.0    # [v9] 0=desactivado. Activar: --config '{"partial_exit_pct":200.0}'
partial_exit_size       = 0.33   # [v9] fraccion a vender en partial exit
lookback_hours          = 15000  # 625 dias (~87 semanas) para EMA350D del Pi Cycle Top
```

### Cache de indicadores
- `_daily_cache`: dict {"date": "YYYY-MM-DD", "ind": {...}}
- `_weekly_cache`: dict {"week": "YYYY-Www", "ind": {...}}
- `_4h_cache`: dict {"key": "YYYY-MM-DD-N", "ind": {...}} (N = hora // 4)

### Shorts sinteticos (cuando allow_shorts=True)
No son ordenes reales de venta en OKX. El margen USDT se reserva via `adjust_balance()`
al abrir y se libera con P&L neto al cerrar. Se registran via `_log_short_trade()`.

**CRITICO:** `OrderResult` requiere `size` y `limit_price`. No omitirlos.

---

## 9. ESTRATEGIA: SCALP MOMENTUM (scalp_momentum.py)

**Estado: EN EVALUACION. Backtests actuales muestran profit factor < 1.**
**Ultima actualizacion: hardgates 1H+4H+D, min_hold_bars=8, no macro filters.**

### Diseno
Day trading en barras de 15 minutos con contexto de 1H (HARD GATE), 4H y diario.

### Timeframes
| Timeframe | Indicadores |
|-----------|-------------|
| 15m | EMA9/21/50, MACD(5,13,3), RSI(9), BB(20), VWAP diario, vol spike direccional |
| 1H | EMA20/50, MACD(12,26,9) → trend_up/down (HARD GATE para entrar) |
| 4H | EMA20/50 → trend_up (filtro adicional) |
| Diario | EMA50D → trend_up (precio vs EMA50D) |

### Sistema de puntuacion (max 10 pts por lado)
**Long:**
- +2 1H trend_up (hard gate)
- +1 EMA9 > EMA21 en 15m
- +1 EMA21 > EMA50 en 15m
- +2 MACD crossover alcista (+1 si solo histograma > 0)
- +1 RSI(9) entre 50-72 (zona EXCLUSIVA longs — no solapa con shorts)
- +1 precio > VWAP diario
- +1 precio > BB mid
- +1 vol expandido + vela alcista (direccional)

**Short:** mirror con zonas RSI 28-50 exclusivas

### Condiciones de entrada
```
long_ok = (
    ls >= 7                     # 7/10 pts
    AND ls >= ss + 3            # ventaja 3 pts sobre shorts
    AND h1_trend_up             # HARD GATE 1H
    AND h1_macd_above           # 1H MACD positivo
    AND h4_trend_up             # 4H tambien alcista
    AND daily_trend_up          # precio > EMA50D diaria
)
```

### Condiciones de salida
1. Hard stop: -6% desde entrada
2. ATR stop (ATR × 1.5)
3. Take profit (ATR × 3.0) — HARD EXIT
4. Score floor < 2 (solo tras min_hold_bars=8)

**MACD cross exit eliminado** — cortaba ganadores antes del TP.

### ScalpMomentumConfig — parametros clave
```python
entry_score_min  = 7      # 7/10 pts
entry_score_gap  = 3      # ventaja minima (era 2, subido para reducir ruido)
min_hold_bars    = 8      # 2 horas minimas antes de exits suaves
size_long        = 0.15   # 15% del capital por operacion
size_short       = 0.10   # 10% para shorts
cooldown_bars    = 8      # 8 barras × 15m = 2h de cooldown
max_loss_pct     = 6.0    # hard stop al -6%
atr_stop_mult    = 1.5
atr_tp_mult      = 3.0
lookback_bars    = 3000   # ~31 dias de datos a 15m
```

### Resultados backtest (2022-2026, 15m)
- 5431 trades cerrados, win rate 37.4%, P&L total: -$3,602 (profit factor 0.75)
- **Estrategia no rentable en el estado actual** — pendiente optimizacion

---

## 10. MACRO CONTEXT (strategies/macro_context.py)

### Proposito
MVRV ratio y ciclo de halving — senales que no pueden derivarse del OHLCV.

### MVRV Ratio
- Fuente: CoinMetrics Community API (gratuito, sin API key)
- Umbrales en codigo (`macro_context.py`):
  - MVRV_DEEP_BEAR = 1.0 → deep_bear
  - MVRV_CHEAP     = 2.0 → recovery (< 2.0)
  - MVRV_FAIR      = 2.5 → bull (2.0-2.5). A partir de aqui: `long_reduce_risk = True`
  - MVRV_LATE_BULL = 3.5 → late_bull (2.5-3.5)
  - MVRV_EUPHORIA  = 4.5 → euphoria (3.5-4.5), "euphoria" si > 4.5
- `short_allowed = False` si MVRV < 2.0
- `long_reduce_risk = True` si regime en "late_bull" o "euphoria" (MVRV >= 2.5)
- **IMPORTANTE:** El maximo MVRV historico en los backtests 2018-2026 fue ~2.96 (Q2 2021).
  Con MVRV_FAIR = 3.0 (anterior), `long_reduce_risk` NUNCA se activaba. El cambio a 2.5
  hace que MVRV 2.96 (Q2 2021) y 2.53 (Q2 2024) bloqueen nuevas entradas long.

### Halving Cycle
Fechas exactas hardcodeadas:
- 28 Nov 2012, 9 Jul 2016, 11 May 2020, 20 Abr 2024, ~15 Mar 2028 (estimado)

Fases:
- post_halving (0-180 dias): shorts bloqueados
- bull_peak (180-540 dias): shorts bloqueados
- bear_onset (540-900 dias): shorts permitidos con MVRV
- accumulation (>900 dias): shorts permitidos con MVRV

### Como se carga
```python
from strategies.macro_context import load_macro_context, get_macro_signal

load_macro_context(from_dt, to_dt)   # fetch API una vez
signal = get_macro_signal(dt)        # O(1) por fecha
```

Se llama automaticamente en `_run_backtest()` de main.py.

### Modo degradado
Si falla CoinMetrics: `short_allowed=True`, `long_reduce_risk=False` — la estrategia
sigue funcionando con sus otros filtros.

---

## 11. MARKET CONTEXT (strategies/market_context.py)

**NUEVO modulo. Filtros negativos de mercado global para Pro Trend.**

### Proposito
DXY (indice del dolar) y NASDAQ-100 como filtros NEGATIVOS en Pro Trend.
Cuando el dolar se fortalece rapido o el NASDAQ entra en correccion, se bloquean
nuevas entradas long independientemente del score.

### Fuente
Yahoo Finance API publica (sin autenticacion, via urllib).
- DXY: ticker `^DXY`
- NDX: ticker `^NDX`

### Como se carga
```python
from strategies.market_context import load_market_context, get_market_context

load_market_context(from_dt, to_dt)   # fetch Yahoo Finance una vez
ctx = get_market_context(dt)          # {dxy_headwind, risk_off, dxy_change, ndx_change}
```

### Senales generadas
- `dxy_headwind`: True si DXY subio > 1.5% en los ultimos 10 dias → adverso para BTC
- `risk_off`: True si NASDAQ bajo > 5% en los ultimos 10 dias → entorno risk-off

### Modo degradado
Si falla Yahoo Finance: `dxy_headwind=False`, `risk_off=False` — filtros desactivados,
Pro Trend opera solo con sus otros filtros.

### Integracion
Cargado en `_run_backtest()` junto a `load_macro_context()`.
Consultado en cada tick de Pro Trend: `get_market_context(current_time)`.

---

## 12. RESULTADOS DE BACKTEST

| Estrategia | Periodo | Balance Final | P&L | Trades | Win Rate | PF | CAGR |
|------------|---------|--------------|-----|--------|----------|----|------|
| BTC Buy & Hold | 2018-2026 | ~$64,971 | +550% | — | — | — | +24.5%/ano |
| Adaptive Trend | 2018-2024 | ~$50,900 | +409% | — | — | — | — |
| Pro Trend v9 | 2018-2026 | PENDIENTE | ? | ? | ? | ? | ? |
| Pro Trend v8 (macd_exit=False) | 2018-2026 | $30,310 | +203% | 11 | 45.5% | 3.73 | +14.9%/ano |
| Pro Trend v7 (macd_exit=True) | 2018-2026 | $21,733 | +117% | 18 | 33.3% | 2.94 | +10.2%/ano |
| Scalp Momentum v5 | 2022-2026 | PENDIENTE | ? | ? | ? | ? | ? |
| Scalp Momentum v4 | 2022-2026 | $9,640 | -3.6% | 351 | 52.4% | 0.93 | -0.8%/ano |

**META: superar BTC B&H (+550%, CAGR +24.5%)**

### Analisis Pro Trend v8 — por que pierde vs B&H (brecha $35k)
- 11 trades, 31% tiempo en mercado (B&H = 100%)
- Trade 5 (Aug-Sep 2021): trailing 22% disparo en crash Evergrande. BTC fue a $67k. Costo: ~$10k
- Trade 8+9 (Q2/Q3 2024): re-entrada 28 dias despues del ATR stop en mismo precio. Trade 9 = -$1,951
- Sizing subdimensionado: score=9 en post_halving = 60% cuando deberia ser 75%

### Pro Trend v9 — cambios implementados (SIN BACKTEST AUN)
- trailing_stop_pct_bull=0.28: 28% en post_halving/bull_peak (vs 22% universal)
  → Trade 5: pico $52k, trail 28%=$37.4k, crash Sept=$40k NO dispara. Ahorro: ~$2,500
- cooldown_atr_stop_days=30: 30 dias tras ATR stop (era 5)
  → Trade 9 bloqueado (28d < 30d). Ahorro: $1,951
- Sizing bull: score>=8 en bull_phase → 75% (era solo score>=10)
  → Trade 4+10 amplificados: +$4,273 adicionales
- partial_exit_pct=0.0 (desactivado, para ablacion): venta parcial en ganancias extremas
- peak_gain_pct en journal: diagnostico del maximo no realizado por trade

### Por que Adaptive sigue superando a Pro Trend (2018-2024)
1. Tamano: Adaptive usa 80% vs Pro 40-75%
2. Pro Trend tiene 11 trades en 8 anos — poco tiempo en mercado
3. La concentracion en 1-2 trades mega-winners es un riesgo de fragildad

---

## 13. TRADE JOURNAL (reporting/trade_journal.py)

**Sistema automatico de registro exhaustivo por backtest.**

### Como funciona
Al finalizar cada backtest, `_run_backtest()` en main.py verifica si la estrategia
tiene entradas en `_journal` y llama a `write_journal()`.

El journal captura en cada apertura y cierre:
- Todos los indicadores (diarios, semanales, 4H, 1H)
- Scores long y short
- Contexto macro (MVRV, halving_phase) y mercado (dxy_change, ndx_change)
- PnL, duracion en horas, razon de salida

### Archivos generados
`backtests/journal_{estrategia}_{simbolo}_{timeframe}_{timestamp}.json`

### Estructura
```json
{
  "meta": {...},
  "statistics": {
    "total_trades": N,
    "win_rate_pct": X,
    "profit_factor": Y,
    "by_exit_reason": {...},
    "win_rate_by_reason": {...}
  },
  "trades": [...]
}
```

---

## 14. BUGS CRITICOS RESUELTOS

### Bug 1: OrderResult constructor (RESUELTO)
`_log_short_trade()` en pro_trend.py no pasaba `size` y `limit_price`.
**Fix:** Añadir `size=qty, limit_price=None` al constructor de OrderResult.

### Bug 2: Oscilacion weekly flip (RESUELTO)
El filtro weekly solo se aplicaba en gestion de posicion abierta, no en ENTRADA.
La estrategia abria long, lo cerraba inmediatamente con weekly_flip_bear, y
volvia a abrir — miles de veces. Balance llega a $0.01 en horas.
**Fix:** `weekly_trend is not False` en `long_ok`, `not True` en `short_ok`.

### Bug 3: Sin cooldown tras weekly flip (RESUELTO)
Re-entrada en la siguiente barra tras cierre semanal.
**Fix:** `_set_cooldown()` — ahora date-based (cooldown_bear_days=30).

### Bug 4: h1["close"] no existia en empty dict (RESUELTO)
`_build_1h_context()` no tenia "close" en el dict de fallback.
**Fix:** Añadir `"close": last_close` al dict de retorno.

### Bug 5: UnicodeEncodeError en Windows (RESUELTO)
Caracteres Unicode en main.py causaban UnicodeEncodeError en cp1252.
**Fix:** Sustituidos por ASCII equivalentes.

---

## 15. LO QUE NO HA FUNCIONADO / DESCARTADO

### Backtests anuales independientes
Ejecutar un BacktestEngine por año con balance reseteado a $10,000 cada 1 de enero.
**Problema:** Las posiciones abiertas desaparecen. El contexto de mercado se pierde.
**Reemplazado por:** Backtest continuo multi-año con equity_curve timestampeada.

### Price reference usando daily["close"] en lugar de h1["close"]
Pro Trend tomaba decisiones usando el cierre diario — artificial.
**Fix:** Usar `h1["close"]` (precio de la barra horaria actual).

### RSI bearish divergence con peso +2 en short score
En bull markets hay divergencias bajistas en cada correccion — ruido.
**Fix:** Reducido a +1.

### Shorts activados en Pro Trend (2018-2026)
Con allow_shorts=True, el sistema shortea en correcciones de bull market y pierde.
Los filtros MVRV+halving reducen el problema pero no lo eliminan.
**Decision:** allow_shorts=False por defecto. Se puede activar para analisis.

### MACD cross exit en ScalpMomentum
Cortaba los ganadores antes de llegar al TP.
**Fix:** Eliminado. Solo ATR stop, TP y score floor para ScalpMomentum.

---

## 16. MEJORAS IDENTIFICADAS Y PENDIENTES

### Alta prioridad
- [x] **MACD exit eliminado en Pro Trend**: RESUELTO. macd_exit_enabled=False por defecto.
      +203% vs +117% con MACD exit — fragmentaba tendencias grandes en trades pequenos.
- [ ] **ScalpMomentum v5**: implementados ADX+Weekly+Macro+Market+TrailingStop. Pendiente backtest.
      `python3 main.py backtest --strategy scalp --from 2022-01-01 --to 2026-06-01 --timeframe 1H`
- [ ] **Analizar Adaptive Trend 2023**: perdio el rally de +155% ese año.
      Analizar si el regimen bull/bear se activo correctamente.

### Media prioridad
- [x] **Pi Cycle Top Indicator**: IMPLEMENTADO. SMA111D > 2×SMA350D. Accion configurable:
      exit_full (defecto) | exit_half | block_entries via `pi_cycle_action` en ProTrendConfig.
- [ ] **Ablation Pro Trend v8**: probar entry_rsi_max y entry_max_ema20_atr.
      CUIDADO: entry_rsi_max=72 bloquearia el trade Oct23 (RSI=74, +$7,148 en v8).
      `python3 main.py backtest --strategy pro --from 2018-01-01 --to 2026-01-01 --config '{"entry_rsi_max": 72}'`
      `python3 main.py backtest --strategy pro --from 2018-01-01 --to 2026-01-01 --config '{"entry_max_ema20_atr": 2.5}'`
- [ ] **Open Interest OKX**: complementar funding rate con OI.
      Endpoint: `/api/v5/public/open-interest`
- [ ] **CVD (Cumulative Volume Delta)**: divergencia CVD/precio. Solo si hay fuente fiable.

### Baja prioridad
- [ ] **Optimizar rendimiento O(n²)**: resample_to_daily/weekly se procesa completo
      aunque este cacheado. Pendiente.

---

## 17. DATOS EXTERNOS INTEGRADOS

### CoinMetrics Community API (activo)
- Sin autenticacion, gratuito
- Metricas usadas: `CapMVRVCur` + `PriceUSD` (para derivar Realized Price)
- `PriceRealizedUSD` NO disponible en tier gratuito — NO intentar fetchearla
- Realized Price = PriceUSD / CapMVRVCur (equivalente matematico exacto)
- URL metricas: usar `%2C` para separar (comma URL-encoded), no `,` literal

### Yahoo Finance API (activo)
- Sin autenticacion, sin API key
- User-Agent obligatorio (de lo contrario da 403)
- DXY: `^DXY`, NDX: `^NDX`
- Modo degradado silencioso si no responde

### OKX OHLCV historico (activo)
- `fetch_historical_bars()` en core/backtest.py
- Paginacion: 300 velas por request, loop hasta cubrir el rango
- Sin autenticacion para datos publicos

### OKX Funding Rate (activo — solo live)
- `OKXClient.get_funding_rate(symbol)` → `GET /api/v5/public/funding-rate`
- Instancia swap: `BTC-USDT` → `BTC-USDT-SWAP`
- `BacktestClient` devuelve 0.0
- Umbral: > 0.0005 bloquea longs; < -0.0005 bloquea shorts

### Datos pendientes
- Open Interest OKX: `/api/v5/public/open-interest`

---

## 18. CONVENCIONES OBLIGATORIAS

### Codigo
- Todos los importes monetarios: `Decimal`, NUNCA `float`
- Fechas en DB: UTC siempre. Conversion a Europe/Madrid SOLO en reporting/display
- Paper mode por defecto. `TRADING_MODE=live` requiere confirmacion explicita
- Logs con loguru. No usar print() para logs

### Estrategias
- Estrategias no saben si estan en backtest o live — el cliente se lo abstrae
- El estado de cada estrategia persiste en BotState (DB) — `_load_state()` / `_save_state()`
- `OrderResult` siempre requiere: `order_id, symbol, side, order_type, size, limit_price,
  filled_price, filled_qty, fee, fee_currency, status, is_paper, strategy, timestamp`
  NO omitir `size` ni `limit_price` (errores silenciosos en backtest)

### Backtesting
- Siempre continuo — nunca reiniciar balance en fronteras de año/mes
- Los trimestres son SOLO para display, nunca para logica de estrategia
- Warmup: 625 dias para Pro Trend (EMA350D), 240 para Adaptive, 25 para Scalp
- Barra actual = `_client.current_time()` → timestamp real de la simulacion

### Archivos
- Maximo 800 lineas por archivo
- Modulo unico de indicadores: `strategies/indicators.py`
- `data/indicators.py` es el ANTIGUO — no usar, no modificar

---

## 19. INSTRUCCIONES OBLIGATORIAS PARA FUTURAS SESIONES

1. **Leer este archivo completo antes de implementar cualquier cosa.**

2. **No ejecutar `python main.py ...` automaticamente.** Mostrar el comando y
   dejar que el usuario lo corra en su propia consola.

3. **Antes de cualquier implementacion, revisar que no esta ya hecho.**
   Los bugs 1-5 de la seccion 14 ya estan resueltos — no re-investigar.

4. **El backtest continuo es la unica forma valida de medir estrategias.**
   No hacer backtests anuales separados. Ver seccion 15.

5. **Al modificar OrderResult en _log_short_trade, siempre incluir `size` y `limit_price`.**

6. **El filtro macro (MVRV + halving) Y el filtro mercado (DXY + NASDAQ) se cargan
   automaticamente en `_run_backtest()`.** Para live trading hay que llamar ambos al inicio.

7. **Pro Trend tiene 11 filtros para longs (en orden):**
   score_min=6 → ventaja > 2 → weekly_trend not False → h4_bullish not False
   → MVRV < 2.5 (long_reduce_risk=False) → funding < 0.0005 → DXY no headwind
   → NASDAQ no risk-off → Pi Cycle Top (SMA111D > 2xSMA350D) no activo
   → RSI <= entry_rsi_max (0=off) → precio no extendido ATR (0=off).
   Los gates estan como variables _g_* en run() para diagnostico.

8. **Pro Trend shortcuts DESACTIVADOS por defecto:** `allow_shorts=False`.
   Para activar shorts: pasar config `{"allow_shorts": true}` en backtest o en DB.
   Los 7 filtros de shorts siguen siendo todos necesarios cuando se activan.

9. **Adaptive Trend no usa shorts.** Su ventaja viene de evitar los bear markets.
   No añadir shorts sin analisis previo.

10. **El MACD exit esta DESACTIVADO por defecto** (`macd_exit_enabled=False`).
    Backtest v8 demostro +203% sin MACD vs +117% con MACD — fragmentaba tendencias.
    El trailing stop del 22% absorbe las correcciones intermedias y deja correr.
    NO reactivar el MACD exit sin justificacion backtest clara.

11. **Al crear nuevos indicadores**, añadirlos a `strategies/indicators.py`.
    Actualizar imports en las estrategias que los usen.

12. **Windows + PowerShell**: usar sintaxis PS, no bash. Paths con backslash.
    Para comandos POSIX usar el Bash tool disponible.

13. **Rich Progress en Windows**: `transient=True` funciona bien.
    Caracteres Unicode pueden causar UnicodeEncodeError en cp1252. Usar ASCII.

14. **ScalpMomentum se corre en 1H** (no 15m). El lookback fue aumentado a 4320 barras
    (180 dias) en v5 para soportar EMA20W semanal. Comando correcto:
    `python3 main.py backtest --strategy scalp --from 2022-01-01 --to 2026-06-01 --timeframe 1H`

15. **El cooldown de Pro Trend es DATE-BASED** (`_cooldown_until: "YYYY-MM-DD"`),
    NO de barras. Diferente al cooldown de ScalpMomentum (que si es de barras).

---

## 20. PROXIMOS PASOS PRIORIZADOS

**ESTADO AL CIERRE DE SESION 2026-06-24 (TERCERA sesion):**
**VERSION ACTUAL EN CODIGO: Pro Trend v9. SIN BACKTEST.**

### Paso 1 — INMEDIATO: Correr Pro Trend v9
```bash
python3 main.py backtest --strategy pro --from 2018-01-01 --to 2026-01-01
```
v9 implementa: trailing_stop_pct_bull=0.28, cooldown_atr_stop_days=30, sizing bull 75%.
Comparar resultado con v8 ($30,310, +203%). Si mejora, continuar. Si empeora, diagnosticar.
Ver journal: buscar peak_gain_pct de cada trade para ver hasta donde llego cada uno.

### Paso 2 — Ablacion partial_exit (si v9 mejora v8)
```bash
python3 main.py backtest --strategy pro --from 2018-01-01 --to 2026-01-01 --config '{"partial_exit_pct": 200.0}'
python3 main.py backtest --strategy pro --from 2018-01-01 --to 2026-01-01 --config '{"partial_exit_pct": 150.0}'
```

### Paso 3 — Correr ScalpMomentum v5 (implementado, sin ejecutar)
```bash
python3 main.py backtest --strategy scalp --from 2022-01-01 --to 2026-06-01 --timeframe 1H
```

### Paso 4 — Ablacion entry filters Pro Trend
CUIDADO: entry_rsi_max=72 bloquea Trade 7 (RSI=74.5, +$7,148). Ejecutar DESPUES de ver v9.
```bash
python3 main.py backtest --strategy pro --from 2018-01-01 --to 2026-01-01 --config '{"entry_rsi_max": 72}'
python3 main.py backtest --strategy pro --from 2018-01-01 --to 2026-01-01 --config '{"entry_max_ema20_atr": 2.5}'
```

### Paso 5 — Comparar estrategias
```bash
python3 main.py compare --strategies "adaptive,pro" --from 2018 --to 2026
```

### Paso 6 — Analizar Adaptive 2023
Perdio rally BTC +155% en 2023. Regimen bull requiere EMA50D > EMA200D AND ADX > 20.
Golden cross llego tarde (BTC ya estaba en $25k+). Diagnosticar con logs DEBUG para 2023.
