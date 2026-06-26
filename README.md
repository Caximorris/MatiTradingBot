# OKX Trading Bot

Bot de trading automatizado para OKX con estrategias de trend following, modo paper trading,
backtesting continuo multi-año, informes fiscales automáticos para España (IRPF) y dashboard en terminal.

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

# Comparar estrategias (descarga datos una sola vez)
python main.py compare --strategies "adaptive,pro" --from 2018 --to 2026

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
**Estado: Mejor resultado actual. v11: +641%, CAGR +28.6% (supera BTC B&H).**

Estrategia de trend following multi-timeframe con sistema de puntuación (0–14 pts)
y filtros en capas:

- **Layer 1 (macro):** VIX, MVRV ratio — bloquea entradas en pánico o euforia de ciclo
- **Layer 2 (mercado):** DXY, NASDAQ-100 — bloquea en entornos adversos a BTC
- **Layer 3 (derivados):** Funding rate histórico OKX — bloquea longs cuando el mercado paga por shorts
- **Layer 4 (técnico):** Score 0–14 pts, ADX, MACD cross-timeframe, Pi Cycle Top

**Sizing adaptativo:** 90% / 80% / 60% según fase del ciclo × score.
**Solo longs por defecto** (`allow_shorts=False`).
**~1–2 operaciones por año** — el trailing stop del 22–28% gestiona la salida.

Fuentes de datos externas cargadas automáticamente antes del backtest:
- MVRV ratio: CoinMetrics Community API (gratuito)
- DXY, NASDAQ-100, VIX: Yahoo Finance
- Funding rate histórico: OKX API

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
indicadores, scores, contexto macro y razón de salida de cada operación.

### Resultados actuales (balance inicial $10,000)

| Estrategia | Período | Balance | P&L | Trades | Win Rate | PF | CAGR |
|------------|---------|---------|-----|--------|----------|----|------|
| BTC Buy & Hold | 2018–2026 | ~$65k | +550% | — | — | — | +24.5% |
| **Pro Trend v11** | 2018–2026 | **$74,124** | **+641%** | 11 | 54.5% | 5.61 | **+28.6%** |
| Adaptive Trend | 2018–2024 | ~$51k | +409% | — | — | — | — |

> Pro Trend v12 (con filtros ADX y MACD cross-timeframe) está implementado pero pendiente de backtest.

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
│   ├── pro_trend.py                # Estrategia: multi-timeframe, scoring system (v12)
│   ├── scalp_momentum.py           # Estrategia: day trading 1H con contexto 4H/D
│   ├── macro_context.py            # MVRV + halving cycle (singleton global)
│   ├── market_context.py           # DXY + NASDAQ-100 + VIX (singleton global)
│   └── funding_context.py          # Funding rate histórico OKX (singleton global)
├── execution/
│   ├── order_manager.py
│   └── position_tracker.py
├── reporting/
│   ├── trade_logger.py
│   ├── trade_journal.py            # JSON detallado por backtest
│   ├── fiscal_report.py            # IRPF FIFO, tramos 2026, Excel+JSON
│   └── dashboard.py
├── backtests/                      # Trade Journals JSON generados automáticamente
│   └── STRATEGY_VERSIONS.md        # Historial de versiones y resultados
└── reports/                        # Informes fiscales generados
```
