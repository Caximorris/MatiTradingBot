# OKX Trading Bot

Bot de trading automatizado para OKX con estrategias de trend following y gestión dinámica de allocation BTC/USDT,
modo paper trading, backtesting continuo multi-año, informes fiscales automáticos para España (IRPF) y dashboard en terminal.

---

## Índice

1. [Requisitos](#1-requisitos)
2. [Instalación](#2-instalación)
3. [Configurar el .env](#3-configurar-el-env)
4. [Arrancar en modo paper](#4-arrancar-en-modo-paper)
5. [Pasar a modo real (live)](#5-pasar-a-modo-real-live)
6. [Comandos principales](#6-comandos-principales)
7. [Estrategias disponibles](#7-estrategias-disponibles)
8. [Backtesting](#8-backtesting)
9. [Informe fiscal IRPF](#9-informe-fiscal-irpf)
10. [Estructura del proyecto](#10-estructura-del-proyecto)

---

## 1. Requisitos

- Python 3.12 o superior
- Cuenta en OKX (solo obligatoria para modo live)
- Windows 10/11, macOS 12+ o Linux

```bash
python --version
```

---

## 2. Instalación

```bash
git clone <url-del-repo>
cd MatiTradingBot

python -m venv .venv

# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

---

## 3. Configurar el .env

```bash
cp .env.example .env
```

```env
# Modo de operación — empieza SIEMPRE con paper
TRADING_MODE=paper

# API OKX (solo obligatorias en modo live)
OKX_API_KEY=
OKX_SECRET_KEY=
OKX_PASSPHRASE=
OKX_SANDBOX=true

# Fiscal
FISCAL_YEAR=2025
COST_BASIS_METHOD=FIFO
```

> El archivo `.env` nunca debe subirse a Git (está en `.gitignore`).

---

## 4. Arrancar en modo paper

```bash
# Verificar configuración
python main.py mode

# Arrancar la estrategia Pro Trend en paper
python main.py start --strategy pro --symbol BTC-USDT

# Dashboard en otra terminal
python main.py dashboard

# Estado y últimos trades
python main.py status
python main.py trades --limit 20
```

---

## 5. Pasar a modo real (live)

> **Lee esto antes:**
> - Realiza paper trading mínimo 6 meses con la estrategia que vayas a usar.
> - El bot puede perder dinero. Nunca inviertas más de lo que puedas permitirte perder.
> - Pro Trend hace ~1-2 trades por año — es normal no ver actividad durante semanas.

1. Obtén API keys en [OKX](https://www.okx.com) con permisos de Lectura + Trading.
2. Edita el `.env`:
   ```env
   TRADING_MODE=live
   OKX_SANDBOX=false
   OKX_API_KEY=tu_api_key_real
   OKX_SECRET_KEY=tu_secret_key_real
   OKX_PASSPHRASE=tu_passphrase_real
   ```
3. Arranca con sizing conservador la primera vez:
   ```bash
   python main.py start --strategy pro --symbol BTC-USDT \
     --config '{"size_ultra": 0.45, "size_high": 0.40, "size_mid": 0.30}'
   ```

---

## 6. Comandos principales

```bash
# Live trading
python main.py start --strategy pro --symbol BTC-USDT
python main.py start --strategy adaptive --symbol BTC-USDT
python main.py stop
python main.py status

# Historial de trades
python main.py trades
python main.py trades --symbol BTC-USDT --limit 50

# Backtesting (continuo, multi-año)
python main.py backtest --strategy pro --from 2018-01-01 --to 2026-01-01
python main.py backtest --strategy adaptive --from 2018-01-01 --to 2024-12-31
python main.py backtest --strategy scalp --from 2022-01-01 --to 2026-06-01 --timeframe 1H
python main.py backtest --strategy swing --from 2015-01-01 --to 2026-01-01 --costs realistic
python main.py backtest --strategy swing --symbol ETH-USDT --from 2020-01-01 --to 2026-01-01

# Comparar estrategias (descarga datos una sola vez)
python main.py compare --strategies "adaptive,pro" --from 2018 --to 2026

# Validacion: walk-forward, baselines y sensitivity analysis
python main.py walk-forward --strategy pro --costs realistic
python main.py walk-forward --strategy swing --costs realistic
python main.py baselines --from 2018-01-01 --to 2026-01-01 --costs realistic
python main.py sensitivity --from 2018-01-01 --to 2026-01-01 --costs realistic

# Monte Carlo
python main.py random-backtest --strategy pro --windows 10 --months 24

# Informes fiscales
python main.py report --year 2025
python main.py report --year 2025 --rate 0.91 --losses 500

# Dashboard
python main.py dashboard
```

---

## 7. Estrategias disponibles

### Pro Trend (`--strategy pro`)
**Estado: version actual v13. 2018-2026 realistic: +521.8%, CAGR +25.7% (vs BTC B&H ~+549.7%, CAGR +26.4%).**
**Ventaja real: ~35% tiempo en mercado, evita crashes del -70%. Drawdown max historico ~42.6%.**

Estrategia de trend following multi-timeframe con sistema de puntuación (0–14 pts)
y filtros en capas:

- **Layer 1 (macro):** VIX, MVRV ratio — bloquea entradas en pánico o euforia de ciclo
- **Layer 2 (mercado):** DXY, NASDAQ-100 — bloquea en entornos adversos a BTC
- **Layer 3 (derivados):** Funding rate histórico OKX — bloquea longs cuando el mercado paga por shorts
- **Layer 4 (técnico):** Score 0–14 pts, ADX gate, MACD cross-timeframe, Pi Cycle Top

**Sizing adaptativo:** 90% / 80% / 60% según fase del ciclo × score.
**Partial exit v13:** vende 33% de la posicion al +150% de ganancia.
**Solo longs por defecto** (`allow_shorts=False`).
**~1–2 operaciones por año** — el trailing stop del 22–28% gestiona la salida.

Fuentes de datos externas cargadas automáticamente antes del backtest:
- MVRV ratio: CoinMetrics Community API (gratuito)
- DXY, NASDAQ-100, VIX: Yahoo Finance
- Funding rate histórico: OKX API

### Swing Allocator (`--strategy swing`)
**Estado: v4 (default) — validado con walk-forward 4/4 ✅, ETH ✅, costs conservative ✅.**
**BTC 2015-2026 realistic: +86.2% CAGR, $9.31M, 68 trades, Max DD -52.71%.**
**Bate a BTC Buy & Hold en retorno Y en riesgo: +86.2% vs +66.8% CAGR, y -52.7% vs -83.8% de drawdown máximo.**

Gestión dinámica de allocation BTC/USDT. Nunca sale completamente de BTC — ajusta el porcentaje
entre 20% y 100% según señales macro y de ciclo. Objetivo: acumular más BTC en correcciones
y reducir exposición antes de bear markets.

- **Señal de régimen:** EMA50D vs EMA200D + ADX — detecta bull/bear macro
- **Señal de halving:** fases post-halving (180-540d) y bear_onset (540d+) — ajusta exposición por ciclo
- **Allocation neutral:** 60% BTC. Bull: +20% → 80%. Post-halving: +20% adicional → 100%. Bear profundo: hasta 20%
- **v4 (default):** floor bajado a 20% + `delta_bear_onset` −30% → más USDT en bear profundo para recomprar
  más barato. Sobre v3, hereda `regime_off_on_bear_onset=True` (suprime la compra de régimen en
  `bear_onset`) y el cap EMA50D en techos de ciclo (`bull_peak_ema50_cap=0.85`).
  Rollback a v3: `--config '{"min_btc_pct": 0.30, "delta_bear_onset": -0.20}'`
- **Rebalanceo automático** cuando la diferencia entre actual y target supera el 10%, con cooldown de 3 días
- **Funciona en ETH** (+56.4% CAGR 2020-2026) — el régimen es causal, no fitting de BTC

**Por qué gana a Buy & Hold:** el USDT preservado en bear markets compra BTC barato en la recuperación.
Ejemplo: en 2022 (BTC -77%) el Swing Allocator baja al 20% BTC, preserva capital, y compra a precios bajos
para el bull run 2023-2025.

```bash
# Backtest BTC 2015-2026
python main.py backtest --strategy swing --from 2015-01-01 --to 2026-01-01 --costs realistic

# Walk-forward para validar robustez
python main.py walk-forward --strategy swing --costs realistic
```

### Adaptive Trend (`--strategy adaptive`)
**Estado: Funcional. Resultado: +409% (2018–2024).**

Estrategia de 3 capas: detección de régimen (bull/bear/range con EMA50D/200D + ADX),
entrada en cruce MACD + RSI 40–70 + volumen, salida por cambio de régimen o ATR stop.
Sizing fijo 80%. Solo longs.

### Scalp Momentum (`--strategy scalp`)
**Estado: En evaluación. v4: profit factor 0.93 (no rentable).**

Day trading en barras de 1H con contexto 4H y diario. Sistema de puntuación 0–10 pts,
filtros ADX, weekly y macro. Múltiples versiones en evaluación.

---

## 8. Backtesting

El motor de backtesting es **continuo** — el balance nunca se reinicia entre años.
Las estrategias se ejecutan sobre datos históricos reales de OKX sin cambiar una línea de código.

```bash
# Pro Trend 2018-2026
python main.py backtest --strategy pro --from 2018-01-01 --to 2026-01-01

# Scalp en 1H (no 15m)
python main.py backtest --strategy scalp --from 2022-01-01 --to 2026-06-01 --timeframe 1H

# Con config personalizada
python main.py backtest --strategy pro --from 2018-01-01 --to 2026-01-01 \
  --config '{"entry_score_min": 8, "size_ultra": 0.70}'

# Comparar todas las estrategias
python main.py compare --strategies "adaptive,pro" --from 2018 --to 2026
```

El backtest genera automáticamente un Trade Journal JSON en `backtests/` con todos los
indicadores, scores, contexto macro, sizing/gates de entrada y razón de salida de cada operación.

### Swing Allocator v4 vs BTC Buy & Hold — comparativa completa

Balance inicial **$10,000**, ventana **2015-01-01 → 2026-01-01**, costes **realistic** (0.1% fee + 5 bps
slippage). Ambas columnas se calculan sobre el **mismo dataset** (102931 velas 1H) y con la **misma
metodología** (Sharpe/Sortino sobre retornos horarios, anualización 8760; drawdown sobre cierres horarios).

| Métrica | 📈 Swing Allocator v4 | ₿ BTC Buy & Hold | Ventaja Swing |
|---|---:|---:|:---:|
| **Balance final** | **$9,307,178** | $2,779,425 | **3.3×** |
| Retorno total | +92,971.78% | +27,694.25% | ✅ |
| **CAGR** | **+86.2%** | +66.8% | **+19.4 pp** |
| **Max Drawdown** | **−52.71%** | −83.77% | **+31.1 pp** menos caída |
| Duración del peor DD | 260 días | 363 días | ✅ −103 días |
| **Calmar** (CAGR/MaxDD) | **1.63** | 0.80 | **2.0×** |
| Sharpe Ratio | 1.38 | 1.08 | ✅ |
| Sortino Ratio | 1.57 | 1.28 | ✅ |
| Tiempo en mercado | 100% | 100% | = |
| — *métricas de trading* — | | | |
| Nº de operaciones | 68 | 1 (hold) | — |
| Win rate | 57.4% | — | — |
| Profit Factor | 4.43 | — | — |
| Expectancy / trade | +55,752 USDT | — | — |
| Median trade | +602 USDT | — | — |
| Avg Win / Avg Loss | +125,541 / −38,101 USDT | — | — |
| Máx. racha perdedora | 6 | — | — |

**Lectura rápida:** el Swing v4 **gana en las dos dimensiones que importan** — más retorno (Calmar 2× el
de B&H) y **mucho menos riesgo** (evita 31 pp del drawdown). El edge no es "predecir": es preservar USDT
en el bear para recomprar barato. El drawdown residual (−52.7%) es el suelo estructural de un long-only
~100% en mercado — nace en los **techos de ciclo** (bull_peak), no en los bears.

> **Nota metodológica honesta:** el resultado es **sensible al punto de inicio** del histórico (el PF
> especialmente). Por eso las anclas de comparación son **CAGR y Max Drawdown** (estables), no el PF.
> Validado además con walk-forward 4/4 ✅, cross-validation en ETH ✅ y costes conservative ✅.

### Otras estrategias (balance inicial $10,000, costes realistic)

| Estrategia | Periodo | Balance | P&L | Trades | Win Rate | PF | CAGR |
|------------|---------|---------|-----|--------|----------|----|------|
| Swing Allocator v4 | 2018-2026 | $226k | +2,158.6% | 49 | 46.9% | 4.17 | +47.6% |
| Swing Allocator v4 ETH | 2020-2026 | $147k | +1,365% | 37 | 59.5% | 2.80 | +56.4% |
| Swing v3 (rollback) | 2015-2026 | ~$7,420k | +73,900% | — | — | — | +82.4% |
| Pro Trend v13 *(pausado)* | 2018-2026 | $62k | +521.8% | 12 | 50.0% | ~4.6 | +25.7% |
| Pro Trend v13 *(pausado)* | 2015-2026 | ~$591k | +5,812% | 20 | 55.0% | ~5.0 | +44.9% |
| Adaptive Trend | 2018-2026 | ~$48k | +380.9% | 20 | — | 2.91 | +21.8% |

> **Pro Trend v13 está pausado** (foco actual: Swing Allocator). ~35% tiempo en mercado, evita crashes
> del -70%. Su ventaja es el riesgo, no el retorno absoluto.

---

## 9. Informe fiscal IRPF

```bash
# Informe del año fiscal 2025 (declaración 2026)
python main.py report --year 2025

# Con tipo de cambio y pérdidas arrastradas
python main.py report --year 2025 --rate 0.91 --losses 500.00
```

El informe se guarda en `reports/informe_fiscal_2025.xlsx` y `.json`.

- **Método FIFO** — obligatorio según la AEAT (consulta vinculante V0999-18)
- **Tramos IRPF 2026:** 19% / 21% / 23% / 28%
- **Compensación de pérdidas** hasta 4 años

---

## 10. Estructura del proyecto

```
MatiTradingBot/
├── main.py                         # CLI typer — todos los comandos
├── requirements.txt
├── config/
│   └── settings.py                 # Settings frozen dataclass, fail-fast en startup
├── core/
│   ├── database.py                 # Trade/Position/BotState + CRUD helpers, WAL SQLite
│   ├── exchange.py                 # OKXClient (paper+live), OrderResult, RateLimiter
│   ├── backtest.py                 # BacktestClient + BacktestEngine + fetch_historical_bars
│   └── risk_manager.py             # can_open_position, calculate_position_size
├── strategies/
│   ├── base_strategy.py            # Clase abstracta con journal helpers
│   ├── indicators.py               # UNICO modulo de indicadores activo
│   ├── adaptive_trend.py           # Estrategia: régimen bull/bear/range, solo longs
│   ├── pro_trend.py                # Estrategia: multi-timeframe, scoring system (v13)
│   ├── scalp_momentum.py           # Estrategia: day trading 1H con contexto 4H/D
│   ├── swing_allocator.py          # Estrategia: allocation dinámica BTC/USDT 20-100% (v4)
│   ├── macro_context.py            # MVRV + halving cycle (singleton global)
│   ├── market_context.py           # DXY + NASDAQ-100 + VIX (singleton global)
│   └── funding_context.py          # Funding rate histórico OKX (singleton global)
├── execution/
│   ├── order_manager.py
│   └── position_tracker.py
├── reporting/
│   ├── trade_logger.py
│   ├── trade_journal.py            # JSON detallado por backtest Pro Trend
│   ├── swing_journal.py            # JSON detallado por backtest Swing Allocator
│   ├── fiscal_report.py            # IRPF FIFO, tramos 2026, Excel+JSON
│   └── dashboard.py
├── backtests/                      # Trade Journals JSON generados automáticamente
│   └── STRATEGY_VERSIONS.md        # Historial de versiones y resultados
└── reports/                        # Informes fiscales generados
```
