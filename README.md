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
**Estado: v2 — validado con walk-forward 4/4 ✅, ETH ✅, costs conservative ✅.**
**BTC 2015-2026 realistic: +80.6% CAGR, $6.69M, 58 trades, Max DD -55.23%.**
**Supera BTC Buy & Hold (~+66.8% CAGR) con menor drawdown máximo histórico (-55.2% vs -77%).**

Gestión dinámica de allocation BTC/USDT. Nunca sale completamente de BTC — ajusta el porcentaje
entre 30% y 100% según señales macro y de ciclo. Objetivo: acumular más BTC en correcciones
y reducir exposición antes de bear markets.

- **Señal de régimen:** EMA50D vs EMA200D + ADX — detecta bull/bear macro
- **Señal de halving:** fases post-halving (180-540d) y bear_onset (540d+) — ajusta exposición por ciclo
- **Allocation neutral:** 60% BTC. Bull: +20% → 80%. Post-halving: +20% adicional → 100%. Bear: −20% → 40%
- **v2 (default):** en `bear_onset` (fase de distribución post-halving) suprime solo la señal de compra
  del régimen — evita perseguir breakouts alcistas que son trampas de ciclo tardío. Mejora CAGR y
  drawdown a la vez. Reversible a v1 con `--config '{"regime_off_on_bear_onset": false}'`
- **Rebalanceo automático** cuando la diferencia entre actual y target supera el 10%, con cooldown de 3 días
- **Funciona en ETH** (+56.4% CAGR 2020-2026) — el régimen es causal, no fitting de BTC

**Por qué gana a Buy & Hold:** el USDT preservado en bear markets compra BTC barato en la recuperación.
Ejemplo: en 2022 (BTC -77%) el Swing Allocator baja a 30% BTC, preserva capital, y compra a precios bajos
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

### Resultados actuales (balance inicial $10,000, costes realistic)

| Estrategia | Periodo | Balance | P&L | Trades | Win Rate | PF | CAGR |
|------------|---------|---------|-----|--------|----------|----|------|
| BTC Buy & Hold | 2015-2026 | ~$2.78M | +27,694% | — | — | — | ~+66.8% |
| BTC Buy & Hold | 2018-2026 | ~$65k | +549.7% | — | — | — | +26.4% |
| **Swing Allocator v2** | **2015-2026** | **$6,690k** | **+66,804%** | **58** | **62.1%** | **6.14** | **+80.6%** |
| **Swing Allocator v2** | **2018-2026** | **$161k** | **+1,510%** | **44** | **52.3%** | **5.54** | **+41.5%** |
| Swing Allocator v2 ETH | 2020-2026 | $147k | +1,365% | 37 | 59.5% | 2.80 | +56.4% |
| Swing Allocator v1 (rollback) | 2015-2026 | $5,810k | +57,996% | 65 | 55.4% | 4.33 | +78.4% |
| **Pro Trend v13** | 2018-2026 | $62k | +521.8% | 12 | 50.0% | ~4.6 | +25.7% |
| Pro Trend v13 | 2015-2026 | ~$591k | +5,812% | 20 | 55.0% | ~5.0 | +44.9% |
| Adaptive Trend | 2018-2026 | ~$48k | +380.9% | 20 | — | 2.91 | +21.8% |

> **Swing Allocator v2 validado:** walk-forward 4/4 ✅, ETH cross-validation ✅, costs conservative ✅.
> v2 mejora CAGR (+2.2pp) y drawdown (-2.4pp) sobre v1 arreglando el ping-pong de mercado lateral.
> No requiere salir completamente de BTC — opera como rebalanceo gradual, compatible con holding a largo plazo.

> **Pro Trend v13:** ~35% tiempo en mercado, evita crashes del -70%. Ventaja real: riesgo, no retorno absoluto.
> Journals con partial exits incluyen `true_pnl_usdt`, sizing real/planificado y giveback desde MFE.

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
│   ├── swing_allocator.py          # Estrategia: allocation dinámica BTC/USDT 30-100% (v2)
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
