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
**Estado: v5 post-audit (default congelado) — validado con walk-forward 4/4, ETH, costs conservative y auditoria post-implementacion.**
**BTC 2015-2026 realistic: +85.84% CAGR, $9.14M, 70 rebalanceos, Max DD -52.73%.**
**Bate a BTC Buy & Hold en retorno Y en riesgo: +85.84% vs +66.6% CAGR, y -52.7% vs -83.8% de drawdown maximo.**

Gestión dinámica de allocation BTC/USDT. Nunca sale completamente de BTC — ajusta el porcentaje
entre 20% y 100% según señales macro y de ciclo. Objetivo: acumular más BTC en correcciones
y reducir exposición antes de bear markets.

- **Señal de régimen:** EMA50D vs EMA200D + ADX — detecta bull/bear macro
- **Señal de halving:** fases post-halving (180-540d) y bear_onset (540d+) — ajusta exposición por ciclo
- **Allocation neutral:** 60% BTC. Bull: +20% → 80%. Post-halving: +20% adicional → 100%. Bear profundo: hasta 20%
- **v5 post-audit (default):** v4 + `daily_on_closed_only=True`; todos los indicadores diarios usan
  dias cerrados para cumplir la regla anti-lookahead. Mantiene floor 20% + `delta_bear_onset` -30%
  para preservar mas USDT en bear profundo y recomprar mas barato. Sobre v3, hereda
  `regime_off_on_bear_onset=True` (suprime la compra de regimen en
  `bear_onset`) y el cap EMA50D en techos de ciclo (`bull_peak_ema50_cap=0.85`).
  Rollback a v3: `--config '{"min_btc_pct": 0.30, "delta_bear_onset": -0.20}'`
  Rollback a v4 congelado: `--config '{"daily_on_closed_only": false}'`
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

### Swing Allocator v5 post-audit vs BTC Buy & Hold — comparativa completa

Balance inicial **$10,000**, ventana **2015-01-01 → 2026-01-01**, costes **realistic** (0.1% fee + 5 bps
slippage). Ambas columnas se calculan sobre el **mismo dataset** (102931 velas 1H) y con la **misma
metodología** (Sharpe/Sortino sobre retornos horarios, anualización 8760; drawdown sobre cierres horarios).

| Métrica | Swing Allocator v5 | BTC Buy & Hold | Ventaja Swing |
|---|---:|---:|:---:|
| **Balance final** | **$9,137,546** | $2,742,741 | **3.3x** |
| Retorno total | +91,275.46% | +27,327.41% | si |
| **CAGR** | **+85.84%** | +66.6% | **+19.2 pp** |
| **Max Drawdown** | **-52.73%** | -83.77% | **+31.0 pp** menos caida |
| Underwater max | 922 dias | — | informar, no maquillar |
| **Calmar** (CAGR/MaxDD) | **1.63** | 0.80 | **2.0×** |
| Sharpe Ratio | 1.38 | 1.08 | si |
| Sortino Ratio | 1.57 | 1.28 | si |
| Tiempo en mercado | 100% | 100% | = |
| — *rebalanceos* — | | | |
| Nº de rebalanceos | 70 | 1 (hold) | — |
| BTC final vs B&H | 0.8171x | 1.0000x | menos BTC, mas USDT |

**Lectura rapida:** el Swing v5 **gana en las dos dimensiones contables principales** — mas retorno
y menos drawdown que B&H. La verdad incomoda es que termina con menos BTC que un holder puro
(`btc_vs_bnh=0.8171`), asi que la tesis es maximizar valor USDT ajustado por ciclo, no acumular mas
BTC nominal que B&H.

> **Nota metodológica honesta:** las métricas por trade del Swing (PF, win-rate, expectancy) son
> realizadas por rebalanceo y no deben usarse como veredicto del allocator. Por eso las anclas de
> comparacion son **CAGR, Max Drawdown, Calmar y BTC vs B&H**, no el PF.
> v5 esta congelado para paper/forward; capital real requiere validacion paper.
>
> **Ruta tool vs ruta CLI:** estas cifras salen de `tools/swing_v5_freeze_report.py`. El comando
> `main.py backtest --strategy swing` da $9.164M / +85.9% en la misma ventana — NO es regresion:
> difiere la contabilidad del warmup (CLI analiza 96930 velas, tool 96907; 23 velas en el tramo
> 2014 con huecos), lo que desplaza el INIT y desvia la valoracion USD +0.29%. DD, ratio BTC y
> rebalanceos son identicos. Cada smoke debe comparar contra el numero de su propia ruta.

### Otras estrategias (balance inicial $10,000, costes realistic)

| Estrategia | Periodo | Balance | CAGR | Max DD | Rebalances/trades | Nota |
|------------|---------|---------|------|--------|-------------------|------|
| Swing Allocator v5 | 2015-2026 | $9.14M | +85.84% | -52.73% | 70 | default congelado |
| Swing Allocator v5 | 2018-2026 | $219.8k | +47.14% | -53.72% | 53 | ventana reciente |
| Swing v5 conservative | 2015-2026 | $8.90M | +85.40% | -52.88% | 70 | costes 15 bps |
| 60/40 mensual | 2015-2026 | $540k | +43.71% | -65.01% | 133 | benchmark allocator |
| EMA200D long/flat | 2015-2026 | $1.47M | +57.36% | -74.93% | 388 | benchmark simple |
| DCA semanal | 2015-2026 | $539k | +43.69% | -79.06% | 576 | benchmark DCA |
| Pro Trend v13 *(pausado)* | 2018-2026 | $62k | +25.7% | — | 12 | riesgo, no retorno |

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
│   ├── swing_allocator.py          # Estrategia: allocation dinámica BTC/USDT 20-100% (v5)
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
├── tools/                          # Scripts de auditoría/validación (portables Windows+Linux)
│   ├── swing_parity_check.py       # Paridad live vs backtest (F15) — exit 1 si divergen
│   ├── degradation_report.py       # Panel de degradación paper/live (F19)
│   ├── telegram_remote.py          # Control remoto Telegram: /status /report /pause /resume
│   └── tg_send.py                  # Envío de alertas Telegram (usado por cron)
├── deploy/                         # Despliegue en VM (paper 24/7)
│   ├── install_vm.sh               # Instalador idempotente Ubuntu (venv+systemd+cron)
│   ├── matibot.service             # systemd: bot de trading (Restart=always)
│   ├── matibot-telegram.service    # systemd: control remoto
│   └── daily_checks.sh             # cron diario: paridad F15 + degradación F19
├── backtests/                      # Trade Journals JSON generados automáticamente
│   └── STRATEGY_VERSIONS.md        # Historial de versiones y resultados
└── reports/                        # Informes fiscales generados
```

---

## 11. Paper trading en la nube (validación forward del Swing v5)

El Swing v5 está congelado: el siguiente hito **no es más backtest**, es la validación forward
en paper — smoke 24h (F13), 30 días de paridad live/backtest sin divergencias (F15) y panel de
degradación (F19). Corre 24/7 en una VM gratuita (Oracle Cloud Always Free o GCP e2-micro) con
control remoto por Telegram.

**Runbook completo: [`DEPLOY_PAPER.md`](DEPLOY_PAPER.md)** — instalación, operación diaria,
criterios de cierre, semántica de pausas/reinicios y checklist de estado del despliegue.

Resumen de operación una vez desplegado:

| Acción | Cómo |
|---|---|
| Estado (vivo, % BTC, valor) | Telegram `/status` |
| Informe de rebalanceos | Telegram `/report` |
| Pausar / reanudar a distancia | Telegram `/pause` / `/resume` |
| Alertas | Automáticas: cada rebalanceo + paridad diaria (12:10 UTC) |
| Kill switch total | SSH: `python main.py stop` |

Notas clave: en paper **no hay API keys** en el servidor (solo datos públicos de OKX);
`OKX_SANDBOX=false` obligatorio para que los datos sean del exchange real; el estado
(portfolio paper, rebalanceos, cadencia) persiste en disco y sobrevive a reinicios —
systemd relanza los procesos solo.
