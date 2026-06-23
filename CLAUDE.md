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
| aiohttp | Webhooks async (signal_follower) |
| python-telegram-bot | Alertas Telegram |
| openpyxl | Exportacion Excel informes fiscales |
| urllib (stdlib) | Fetch datos externos (CoinMetrics MVRV) — sin requests |

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
│   ├── indicators.py               # UNICO modulo de indicadores activo (ver seccion 6)
│   ├── adaptive_trend.py           # Estrategia 1: regimen bull/bear/range, solo longs
│   ├── pro_trend.py                # Estrategia 2: multi-timeframe, longs + shorts sinteticos
│   ├── macro_context.py            # NUEVO: MVRV + halving cycle (singleton global)
│   ├── mean_reversion.py           # Estrategia auxiliar (BB+RSI, no en backtests activos)
│   └── signal_follower.py          # Estrategia auxiliar (webhook/Telegram)
├── execution/
│   ├── order_manager.py            # Gestion de ordenes
│   └── position_tracker.py        # Tracking de posiciones abiertas
└── reporting/
    ├── trade_logger.py             # TradeLogger.log() + from_order_result()
    ├── fiscal_report.py            # IRPF FIFO, tramos 2026, Excel+JSON (pendiente)
    └── dashboard.py                # Dashboard rich (pendiente)
```

---

## 4. COMANDOS CLI DISPONIBLES

Todos se ejecutan desde `okx_trader/` con `python main.py <comando>`.

```bash
# Backtest continuo de una estrategia (2018-2024 = 7 anos sin fronteras de año)
python main.py backtest --strategy pro --from 2018-01-01 --to 2024-12-31

# Comparar estrategias (descarga barras UNA SOLA VEZ para todas)
python main.py compare --strategies "adaptive,pro" --from-year 2018 --to-year 2024

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

---

## 6. MODULO DE INDICADORES (strategies/indicators.py)

ESTE ES EL UNICO modulo de indicadores activo. `data/indicators.py` es el antiguo — ignorar.

Funciones disponibles:
- `ema(series, period)` → pd.Series
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
- `resample_to_daily(df)` → DataFrame con col "dt"
- `resample_to_weekly(df)` → DataFrame con col "dt"
- `resample_to_4h(df)` → DataFrame con col "dt" (mismo patron que daily/weekly, period="4h")
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

### Por que supera a Pro Trend
Adaptive usa 80% del capital por trade y deja correr los ganadores.
Pro Trend usa 12-20% y sale demasiado pronto.

---

## 8. ESTRATEGIA: PRO TREND (pro_trend.py)

**Estado: FUNCIONAL pero en desarrollo activo. Resultado actual: +49.87%.**

### Diseno
Multi-timeframe con sistema de puntuacion (0-14 pts por lado) + shorts sinteticos.

### Timeframes y indicadores usados
| Timeframe | Indicadores |
|-----------|-------------|
| Semanal | EMA20W, EMA50W, slope → `weekly_trend_up` bool |
| Diario | EMA20D, EMA50D, EMA200D, EMA200D_slope, MACD, RSI, ATR, ADX, OBV, BB, Swing, S/R, FVG, RSI_div, Volume Profile (POC/VAH/VAL) |
| 4H | EMA20/50 4H, MACD 4H, swing 4H → `trend_bullish` / `trend_bearish` bool (cache por bloque de 4h) |
| Horario (1H) | FVG zones, BB squeeze/breakout, vol spike, precio actual |
| Macro (externo) | MVRV ratio, Realized Price derivada, halving cycle phase, funding rate |

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
- +1 precio cerca de soporte
- +1 FVG alcista cercano
- +1 vol spike alcista
- +1 BB dip en tendencia alcista o squeeze breakout up

**Short score** (mirror, con ajustes):
- RSI divergencia bajista: solo +1 (reducido de +2 — en bull markets hay divs bajistas constantemente)
- +1 EMA200D slope negativo (nuevo — confirma tendencia bajista estructural)

### Condiciones de entrada (v4 — actual)
```
long_ok = (
    ls >= 7                             # umbral longs
    AND ls > ss + 2                     # ventaja sobre shorts
    AND weekly_trend is not False       # no entrar long en tendencia semanal bajista
    AND h4["trend_bullish"] is not False # 4H alineado con long
    AND NOT macro["long_reduce_risk"]   # no entrar si MVRV indica euforia
    AND funding < 0.0005                # funding < 0.05% (mercado no sobrecomprado en derivados)
)
short_ok = (
    ss >= 9                             # umbral mas alto para shorts
    AND ss > ls + 2
    AND weekly_trend is not True        # no shortear en tendencia semanal alcista
    AND ema_bear                        # EMA200D declinando + precio < EMA200D
    AND macro["short_allowed"]          # MVRV >= 2.0 Y halving phase no es bull
    AND above_realized                  # precio > Realized Price * 1.1 (titulares no en perdidas)
    AND h4["trend_bearish"] is not False # 4H alineado con short
    AND funding > -0.0005               # funding no muy negativo (no sobrevendido)
)
```

### Derivacion de Realized Price
`PriceRealizedUSD` no esta disponible en CoinMetrics Community (tier gratuito).
Se deriva matematicamente: `realized_price = PriceUSD / MVRV` (equivalente exacto por definicion:
MVRV = MarketCap / RealizedCap = Price / RealizedPrice).
Implementado en `macro_context.py::realized_price_at()`.

### Funding Rate
`OKXClient.get_funding_rate(symbol)` llama a `GET /api/v5/public/funding-rate` (sin auth).
`BacktestClient.get_funding_rate(symbol)` devuelve `0.0` — no hay datos historicos de funding.
El filtro de funding es efectivo solo en live trading.

### Condiciones de salida (por orden de prioridad)
1. Flip semanal (weekly_trend_up cambia) → cierre + cooldown
2. Hard stop si perdida > 20% desde entrada → cierre + cooldown
3. ATR stop (precio cruza ATR×2.5 desde entrada) → cierre + cooldown
4. MACD death cross + precio < EMA20D (longs) / golden cross + precio > EMA20D (shorts)
5. RSI divergencia con ganancia > 20% → reducir 50% (solo una vez por trade)
6. Score cae por debajo de exit_score_floor (3)

### Shorts sinteticos
No son ordenes reales de venta en OKX. El margen USDT se reserva via `adjust_balance()`
al abrir y se libera con P&L neto al cerrar. Se registran via `_log_short_trade()` que
crea un `OrderResult` sintetico.

**CRITICO:** `OrderResult` requiere los campos `size` y `limit_price`. No omitirlos
o se lanza excepcion silenciosa y el trade no se registra.

### Cooldown
Despues de: ATR stop, hard stop, weekly flip → `_set_cooldown()`.
Valor por defecto: 5 barras horarias (configurable en `cooldown_bars`).
Durante cooldown no se abren nuevas posiciones.

### Cache de indicadores
- `_daily_cache`: dict {"date": "YYYY-MM-DD", "ind": {...}} — recalcula 1 vez por dia
- `_weekly_cache`: dict {"week": "YYYY-Www", "ind": {...}} — recalcula 1 vez por semana
- `_4h_cache`: dict {"key": "YYYY-MM-DD-N", "ind": {...}} — recalcula 1 vez por bloque de 4h (N = hora // 4)

### ProTrendConfig — parametros clave
```python
entry_score_min       = 7      # umbral minimo para longs
entry_score_min_short = 9      # umbral minimo para shorts (mas alto)
entry_score_gap       = 2      # ventaja minima sobre score opuesto
exit_score_floor      = 3      # cierra si score baja de esto
size_high             = 0.20   # 20% del USDT si score >= 8
size_mid              = 0.12   # 12% del USDT si score < 8
size_short_cap        = 0.15   # cap maximo para shorts
cooldown_bars         = 5
max_loss_pct          = 20.0   # hard stop al -20%
atr_stop_mult         = 2.5    # ATR × 2.5
lookback_hours        = 8760   # 1 ano de datos horarios (52 semanas)
```

---

## 9. MACRO CONTEXT (strategies/macro_context.py)

**NUEVO modulo implementado en sesion actual.**

### Proposito
Proporcionar senales macro (MVRV y ciclo de halving) que no pueden derivarse del OHLCV.
Resuelve el problema principal de Pro Trend: shortear durante bull markets.

### MVRV Ratio
- Fuente: CoinMetrics Community API (gratuito, sin API key)
- URL: `https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=btc&metrics=CapMVRVCur`
- Umbrales historicos:
  - < 1.0 → deep_bear (fondo, precio bajo coste base del mercado)
  - 1.0-2.0 → recovery (zona barata)
  - 2.0-3.0 → bull
  - 3.0-3.5 → late_bull
  - > 3.5 → euphoria (posible techo)
- `short_allowed = False` si MVRV < 2.0 (mercado barato — no apostar contra el)
- `long_reduce_risk = True` si MVRV > 3.5 (reducir tamano en zona de techo)

### Halving Cycle
Fechas exactas hardcodeadas (bloques minados):
- 28 Nov 2012, 9 Jul 2016, 11 May 2020, 20 Abr 2024, ~15 Mar 2028 (estimado)

Fases:
- post_halving (0-180 dias): mercado en transicion → shorts bloqueados
- bull_peak (180-540 dias): historicamente el bull market → shorts bloqueados
- bear_onset (540-900 dias): inicio bear → shorts permitidos
- accumulation (>900 dias): fondo/pre-halving → shorts permitidos con MVRV

`short_allowed = False` en fases post_halving y bull_peak.

### Como se carga
```python
from strategies.macro_context import load_macro_context, get_macro_signal

load_macro_context(from_dt, to_dt)   # fetch API una vez, cache con guard anti-redundancia
signal = get_macro_signal(dt)        # consulta O(1) por fecha
```

Se llama automaticamente en `_run_backtest()` de main.py antes de la simulacion.
Para live trading habria que llamarlo al inicio con un rango de ~2 anos.

### Modo degradado
Si falla la conexion a CoinMetrics, `short_allowed=True` y `long_reduce_risk=False`
por defecto — la estrategia sigue funcionando con sus otros filtros.

---

## 10. RESULTADOS DE BACKTEST (2018-2024, continuo)

| Estrategia | Balance Final | P&L | Win Rate | Profit Factor | Max DD |
|------------|--------------|-----|----------|--------------|--------|
| BTC Buy & Hold | $68,436 | +584% | — | — | -83% |
| Adaptive Trend | $50,900 | +409% | — | — | N/D |
| Pro Trend v3 | $14,987 | +50% | 51.7% | 2.02 | -30% |

### Por que Adaptive supera a Pro Trend
1. Tamano de posicion: Adaptive usa 80%, Pro usa 12-20%
2. Adaptive deja correr los trades — Pro sale demasiado pronto (RSI div, ATR stop)
3. Pro intenta operar shorts que en bull markets pierden sistematicamente
4. En los grandes bull runs (2020, 2021, 2024) Pro solo captura el 4-8% mientras Adaptive captura el 60-70%

### Trimestres clave de Pro Trend v3
Mejores: Q3 2019 (+$1,965), Q4 2024 (+$581), Q2 2021 (+$987)
Peores: Q3 2024 (-$527), Q1 2023 (-$440), Q2 2024 (-$409)

### Por que siguen fallando Q2-Q3 2024
BTC tuvo correcciones reales del 20-25% que hicieron que el EMA200D cediera
temporalmente, activando el filtro ema_bear y permitiendo shorts que perdieron
cuando BTC se recupero. El filtro MVRV+halving (recien implementado) deberia
resolver esto en el proximo backtest.

---

## 11. BUGS CRITICOS RESUELTOS

### Bug 1: OrderResult constructor (RESUELTO)
`_log_short_trade()` en pro_trend.py no pasaba `size` y `limit_price`.
Cada intento de short lanzaba excepcion silenciosa. El engine la capturaba con
`logger.warning("Backtest tick {}/{}: {}")` y continuaba sin operar.
**Fix:** Añadir `size=qty, limit_price=None` al constructor de OrderResult.

### Bug 2: Oscilacion weekly flip (RESUELTO)
El filtro weekly solo se aplicaba en gestion de posicion abierta, no en la condicion
de ENTRADA. La estrategia abria long con score >= 7, lo cerraba inmediatamente
con weekly_flip_bear, y volvia a abrir en la siguiente barra — miles de veces.
Cada ciclo cobra comision → balance llega a $0.01 en horas.
**Fix:** Añadir `weekly_trend is not False` en `long_ok` y `not True` en `short_ok`.

### Bug 3: Sin cooldown tras weekly flip (RESUELTO)
Despues de cerrar por flip semanal, no habia cooldown — re-entrada en siguiente barra.
**Fix:** `_set_cooldown()` despues de `weekly_flip_bear` y `weekly_flip_bull`.

### Bug 4: h1["close"] no existia en empty dict (RESUELTO)
El dict `empty` de `_build_1h_context()` no tenia la clave "close".
Cuando habia < 30 barras, `price = Decimal(str(h1["close"]))` en run() lanzaba KeyError.
**Fix:** Añadir `"close": last_close` al dict de retorno normal (el empty aun puede fallar
con < 30 barras pero ese caso es solo al inicio del backtest).

### Bug 5: UnicodeEncodeError en Windows (RESUELTO)
Caracteres Unicode en main.py (`→`, `…`, `×`) no eran codificables por cp1252.
**Fix:** Sustituidos por ASCII equivalentes (`->`, `...`, `x`).

---

## 12. LO QUE NO HA FUNCIONADO / DESCARTADO

### Backtests anuales independientes
Ejecutar un BacktestEngine por año con balance reseteado a $10,000 cada 1 de enero.
**Problema:** Las posiciones abiertas el 28 de diciembre desaparecen el 1 de enero.
El contexto de mercado se pierde. Los resultados son artificialmente buenos/malos segun
si el año empieza en maximo o minimo.
**Reemplazado por:** Backtest continuo 2018-2024 con equity_curve timestampeada.

### Price reference usando daily["close"] en lugar de h1["close"]
Pro Trend tomaba todas las decisiones de precio usando el cierre diario.
Los trades se "abrían al principio del día" o "esperaban al cierre".
**Problema:** Artificial y no corresponde a como opera un sistema real.
**Fix:** Usar `h1["close"]` (precio de la barra horaria actual) para todas las decisiones.

### RSI bearish divergence con peso +2 en short score
En bull markets hay divergencias bajistas en cada correcion — era ruido.
Con +2 puntos era facil alcanzar el umbral de short y abrir posiciones perdedoras.
**Fix:** Reducido a +1.

---

## 13. MEJORAS IDENTIFICADAS Y PENDIENTES

### Alta prioridad (impacto directo en rentabilidad)
- [ ] **Tamaño de posicion en Adaptive Trend**: ya usa 80%, evaluar si subir a 90-95%
      para capturar mas del upside en bull markets
- [ ] **Timeframe 4H para Pro Trend**: actualmente salta de 1D a 1H.
      El 4H es el estandar profesional — mejor timing, menos ruido que 1H.
      Implementar `_build_4h_context()` con Order Blocks y CHoCH/BOS
- [ ] **Verificar impacto de MVRV+halving** en Pro Trend: pendiente backtest completo
      con los nuevos filtros. Esperado: eliminar shorts en Q2-Q3 2024

### Media prioridad (mejoran calidad de señales)
- [ ] **Volume Profile / Point of Control**: S/R mas fiable que swing highs/lows
- [ ] **Funding rates de OKX**: OKX da este dato gratis. Funding muy positivo =
      mercado sobrecomprado = no entrar longs. Endpoint: GET /api/v5/public/funding-rate
- [ ] **Fibonacci 0.618 retracement**: en tendencias BTC, el 0.618 Fib del impulso
      es el nivel de reentrada mas fiable estadisticamente
- [ ] **CVD (Cumulative Volume Delta)**: diferencia volumen comprador/vendedor.
      Divergencia CVD/precio es señal de inversion antes de que el precio lo confirme

### Baja prioridad
- [ ] **Pi Cycle Top Indicator**: EMA111 cruza 2×EMA350 — ha marcado cada techo BTC
      dentro de 3 dias. Util para salidas de largo plazo
- [ ] **Optimizar rendimiento O(n²)**: resample_to_daily/weekly se llama cada barra
      aunque esten cacheadas, el dataframe completo se procesa igualmente
- [ ] **Adaptive Trend 2023**: perdio el rally de +155% ese año. Analizar por que
      y si el regimen bull/bear se activo correctamente

---

## 14. DATOS EXTERNOS INTEGRADOS

### CoinMetrics Community API (activo)
- Sin autenticacion, gratuito
- Metricas usadas: `CapMVRVCur` (MVRV ratio) + `PriceUSD` (para derivar Realized Price)
- `PriceRealizedUSD` NO esta disponible en el tier gratuito — NO intentar fetchearla
- Realized Price = PriceUSD / CapMVRVCur (equivalente matematico exacto)
- Cache: global singleton `_GLOBAL_CTX` en macro_context.py
- Guard anti-redundancia: no re-descarga si el rango ya esta cargado
- URL con metricas: usar `%2C` para separar metricas (comma URL-encoded), no `,` literal

### OKX OHLCV historico (activo)
- `fetch_historical_bars()` en core/backtest.py
- Paginacion: 300 velas por request, loop hasta cubrir el rango
- Sin autenticacion para datos publicos (endpoint publico de OKX)

### OKX Funding Rate (activo — solo live)
- `OKXClient.get_funding_rate(symbol)` → `GET /api/v5/public/funding-rate`
- Instancia swap: `BTC-USDT` → `BTC-USDT-SWAP`
- `BacktestClient` devuelve 0.0 (no hay datos historicos de funding gratuitos)
- Umbral: funding > 0.0005 bloquea longs; funding < -0.0005 bloquea shorts

### Datos pendientes de integrar
- Open Interest OKX: `/api/v5/public/open-interest` (puede complementar el filtro de funding)

---

## 15. CONVENCIONES OBLIGATORIAS

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
- Los trimestres son SOLO para display en tablas, nunca para logica de estrategia
- Warmup: 380 dias para Pro Trend, 240 dias para Adaptive
- Barra actual = `_client.current_time()` → devuelve timestamp real de la simulacion

### Archivos
- Maximo 800 lineas por archivo
- Modulo unico de indicadores: `strategies/indicators.py`
- `data/indicators.py` es el ANTIGUO — no usar, no modificar

---

## 16. INSTRUCCIONES OBLIGATORIAS PARA FUTURAS SESIONES

1. **Leer este archivo completo antes de implementar cualquier cosa.**

2. **No ejecutar `python main.py ...` automaticamente.** Mostrar el comando y
   dejar que el usuario lo corra en su propia consola.

3. **Antes de cualquier implementacion, revisar que no esta ya hecho.**
   Los bugs 1-5 de la seccion 11 ya estan resueltos — no re-investigar.

4. **El backtest continuo es la unica forma valida de medir estrategias.**
   No hacer backtests anuales separados. Ver seccion 12.

5. **Al modificar OrderResult en _log_short_trade, siempre incluir `size` y `limit_price`.**

6. **El filtro macro (MVRV + halving) se carga automaticamente en `_run_backtest`.**
   Para live trading hay que llamar `load_macro_context(from_dt, to_dt)` al inicio.

7. **Pro Trend tiene 6 capas de filtro para shorts (en orden):**
   weekly_trend → ema_bear → MVRV → halving phase → above_realized → 4H trend.
   Todas deben cumplirse. No eliminar ninguna sin justificacion.
   Para longs: weekly_trend → 4H trend → MVRV euforia → funding rate.

8. **Adaptive Trend no usa shorts.** Su ventaja sobre B&H viene exclusivamente de
   evitar los bear markets (-80% en 2018, -75% en 2022). No añadir shorts a Adaptive
   sin analisis previo muy detallado.

9. **El problema principal de Pro Trend vs B&H es el tamaño de posicion (12-20% vs 100%)
   y las salidas prematuras**, no las señales de entrada. Antes de añadir mas indicadores,
   considerar subir el sizing o cambiar la logica de salida.

10. **Al crear nuevos indicadores**, añadirlos a `strategies/indicators.py`, no a ningún
    otro modulo. Actualizar el import en `pro_trend.py` si se necesitan.

11. **Windows + PowerShell**: usar sintaxis PS, no bash. Paths con backslash o comillas dobles.
    Para comandos POSIX usar el Bash tool disponible.

12. **Rich Progress en Windows**: `transient=True` funciona correctamente.
    Caracteres Unicode (flechas, puntos suspensivos) pueden causar UnicodeEncodeError en cp1252.
    Usar solo ASCII en strings de progreso.

---

## 17. PROXIMOS PASOS PRIORIZADOS

1. **Verificar resultados del backtest v4** (en curso — lanzado)
   Comando: `python main.py backtest --strategy pro --from 2018-01-01 --to 2024-12-31`
   Nuevos filtros activos: 4H alignment, Volume Profile S/R, Realized Price, funding rate

2. **Comparar Pro v4 vs Adaptive vs B&H**
   Comando: `python main.py compare --strategies "adaptive,pro" --from-year 2018 --to-year 2024`

3. **Evaluar subir sizing de Pro Trend**: cambiar `size_mid=0.25, size_high=0.40` y rebacktestear
   El problema identificado es que 12-20% deja demasiado capital inactivo

4. **Pi Cycle Top**: EMA111 cruza 2xEMA350 — ha marcado cada techo BTC dentro de 3 dias.
   Util para salidas de largo plazo o reduccion agresiva de posicion

5. **Open Interest OKX**: complementar funding rate con OI para detectar squeeze setups
