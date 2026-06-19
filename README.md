# OKX Trading Bot

Bot de trading automatizado para OKX con múltiples estrategias, modo paper trading,
informes fiscales automáticos para España (IRPF) y dashboard en terminal.

---

## Índice

1. [Requisitos](#1-requisitos)
2. [Instalación](#2-instalación)
3. [Configurar el .env](#3-configurar-el-env)
4. [Obtener API keys de OKX](#4-obtener-api-keys-de-okx)
5. [Arrancar en modo paper](#5-arrancar-en-modo-paper)
6. [Pasar a modo real (live)](#6-pasar-a-modo-real-live)
7. [Comandos principales](#7-comandos-principales)
8. [Estrategias disponibles](#8-estrategias-disponibles)
9. [Informe fiscal IRPF](#9-informe-fiscal-irpf)
10. [Backtesting](#10-backtesting)
11. [Estructura del proyecto](#11-estructura-del-proyecto)

---

## 1. Requisitos

- Python 3.12 o superior
- Cuenta en OKX (solo obligatoria para modo live)
- Windows 10/11, macOS 12+ o Linux

Comprueba tu versión de Python:

```bash
python --version
```

---

## 2. Instalación

```bash
# Clona el repositorio
git clone <url-del-repo>
cd okx_trader

# Crea un entorno virtual (recomendado)
python -m venv .venv

# Activa el entorno virtual
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

# Instala las dependencias
pip install -r requirements.txt
```

---

## 3. Configurar el .env

Copia el archivo de ejemplo y edítalo:

```bash
cp .env.example .env
```

Abre `.env` con cualquier editor y rellena los valores:

```env
# ── Modo de operación ──────────────────────────────────────────────────────
# Empieza SIEMPRE con "paper". Cambiar a "live" requiere API keys reales.
TRADING_MODE=paper

# ── API OKX (solo obligatorias en modo live) ──────────────────────────────
OKX_API_KEY=
OKX_SECRET_KEY=
OKX_PASSPHRASE=
OKX_SANDBOX=true          # true en desarrollo, false en producción real

# ── Pares a operar (separados por coma) ───────────────────────────────────
TRADING_PAIRS=BTC-USDT,ETH-USDT

# ── Gestión de riesgo ─────────────────────────────────────────────────────
MAX_PORTFOLIO_RISK_PCT=2.0   # máx. 2% del portfolio en riesgo por operación
MAX_OPEN_POSITIONS=10
DAILY_LOSS_LIMIT_PCT=5.0     # para el bot si pierde más del 5% en el día

# ── Fiscal ────────────────────────────────────────────────────────────────
FISCAL_YEAR=2025
COST_BASIS_METHOD=FIFO       # obligatorio en España (AEAT)
```

> **Importante:** el archivo `.env` nunca debe subirse a Git.
> Está incluido en `.gitignore` por defecto.

---

## 4. Obtener API keys de OKX

Solo necesitas API keys si vas a operar en modo **live**. En modo paper no hacen falta.

1. Ve a [https://www.okx.com/es/help/how-to-create-api-keys](https://www.okx.com/es/help/how-to-create-api-keys) y sigue los pasos.
2. Al crear la key, activa los permisos: **Lectura** y **Trading**.  
   **No actives "Retirada de fondos"** — el bot no lo necesita.
3. Guarda el API Key, Secret Key y Passphrase en el `.env`.
4. Si quieres probar primero en el entorno de pruebas de OKX:
   - Activa `OKX_SANDBOX=true` en el `.env`
   - Crea las keys en [https://www.okx.com/es/demo-trading](https://www.okx.com/es/demo-trading)

---

## 5. Arrancar en modo paper

El modo paper simula todas las operaciones localmente sin mover dinero real.
Es el modo por defecto y el recomendado para empezar.

```bash
# Verifica la configuración
python main.py mode

# Añade tu primer bot (ejemplo: Grid en BTC-USDT)
python main.py bot add grid BTC-USDT \
  --config '{"upper_price":"70000","lower_price":"60000","num_grids":10,"total_investment":"1000"}'

# Actívalo
python main.py bot enable grid_btc_usdt BTC-USDT

# Arranca el scheduler (Ctrl+C para detener)
python main.py start

# En otra terminal, abre el dashboard
python main.py dashboard
```

Para ver el estado en cualquier momento:

```bash
python main.py status
python main.py trades --limit 20
```

---

## 6. Pasar a modo real (live)

> **Lee esto antes de continuar:**
> - Empieza siempre con cantidades pequeñas.
> - Verifica que la estrategia funciona bien en paper durante al menos 2 semanas.
> - El bot puede perder dinero. Nunca inviertas más de lo que puedas permitirte perder.

Pasos para activar el modo live:

1. Obtén tus API keys de OKX (ver sección 4).
2. Edita el `.env`:
   ```env
   TRADING_MODE=live
   OKX_SANDBOX=false
   OKX_API_KEY=tu_api_key_real
   OKX_SECRET_KEY=tu_secret_key_real
   OKX_PASSPHRASE=tu_passphrase_real
   ```
3. Verifica que el modo cambió:
   ```bash
   python main.py mode
   ```
4. Arranca con un límite de pérdida diaria conservador:
   ```env
   DAILY_LOSS_LIMIT_PCT=2.0
   MAX_PORTFOLIO_RISK_PCT=1.0
   ```

---

## 7. Comandos principales

```bash
# Gestión de bots
python main.py bot list                         # listar bots configurados
python main.py bot add grid BTC-USDT --config '{"upper_price":"70000",...}'
python main.py bot enable grid_btc_usdt BTC-USDT
python main.py bot disable grid_btc_usdt BTC-USDT

# Operación
python main.py start                            # arrancar todos los bots activos
python main.py start --tick 60                  # tick cada 60 segundos
python main.py stop                             # parada de emergencia
python main.py status                           # resumen del sistema
python main.py dashboard                        # dashboard en tiempo real
python main.py dashboard --refresh 60           # refresco cada 60s

# Historial
python main.py trades                           # últimos 20 trades
python main.py trades --symbol BTC-USDT -n 50
python main.py trades --paper                   # solo trades paper
python main.py trades --live                    # solo trades reales

# Fiscal
python main.py report --year 2025
python main.py report --year 2025 --rate 0.91 --losses 500

# Backtesting
python main.py backtest --strategy grid --symbol BTC-USDT \
  --from 2024-01-01 --to 2024-12-31
```

---

## 8. Estrategias disponibles

### Grid Trading
Coloca órdenes de compra y venta en niveles equidistantes dentro de un rango de precio.
Genera beneficios con la volatilidad lateral.

```bash
python main.py bot add grid BTC-USDT --config '{
  "upper_price": "70000",
  "lower_price": "60000",
  "num_grids": 10,
  "total_investment": "1000",
  "auto_adjust": true
}'
```

| Parámetro | Descripción |
|---|---|
| `upper_price` | Límite superior del rango (USDT) |
| `lower_price` | Límite inferior del rango (USDT) |
| `num_grids` | Número de niveles (5–20 recomendado) |
| `total_investment` | USDT total a invertir |
| `auto_adjust` | Reajusta el grid si el precio sale del rango |

### DCA (Dollar Cost Averaging)
Compra a intervalos regulares y añade órdenes de seguridad si el precio baja.

```bash
python main.py bot add dca ETH-USDT --config '{
  "base_order_size": "100",
  "safety_order_size": "100",
  "price_deviation_pct": "2.0",
  "take_profit_pct": "1.5",
  "max_safety_orders": 3,
  "safety_order_volume_scale": "1.5",
  "interval_hours": "24"
}'
```

### Mean Reversion
Compra cuando el precio toca la banda inferior de Bollinger + RSI sobrevendido.
Diseñado para altcoins con alta volatilidad.

```bash
python main.py bot add mean SOL-USDT --config '{
  "symbol": "SOL-USDT",
  "timeframe": "4H",
  "rsi_oversold": "35",
  "rsi_overbought": "65"
}'
```

### Signal Follower (Copytrading)
Ejecuta órdenes basadas en señales externas de TradingView o Telegram.

```bash
# En el .env:
SIGNAL_SOURCE=tradingview_webhook
WEBHOOK_PORT=8080

python main.py bot add signal BTC-USDT
python main.py bot enable signal_follower BTC-USDT
python main.py start
```

Configura tu alerta en TradingView con webhook a `http://tu-ip:8080/signal` y el payload:
```json
{"symbol": "BTC-USDT", "action": "buy", "price": 65000, "risk_pct": 1.0}
```

---

## 9. Informe fiscal IRPF

El bot genera automáticamente un informe de ganancias y pérdidas de criptomonedas
según la normativa española (AEAT, Modelo 100).

```bash
# Genera el informe del año fiscal 2025 (declaración 2026)
python main.py report --year 2025

# Con tipo de cambio USDT/EUR personalizado
python main.py report --year 2025 --rate 0.91

# Con pérdidas arrastradas de años anteriores
python main.py report --year 2025 --losses 500.00
```

El informe se guarda en `reports/informe_fiscal_2025.xlsx` y `reports/informe_fiscal_2025.json`.

### Qué calcula el informe

- **Método FIFO** — obligatorio según la AEAT para criptomonedas (consulta vinculante V0999-18).
  Cada venta se empareja con la compra más antigua del mismo activo.
- **Tramos IRPF 2026** (base del ahorro):
  - 0 – 6.000 €: 19%
  - 6.000 – 50.000 €: 21%
  - 50.000 – 200.000 €: 23%
  - Más de 200.000 €: 28%
- **Compensación de pérdidas** — las pérdidas del año reducen las ganancias;
  el exceso se arrastra hasta 4 años.

### Pestañas del Excel

| Pestaña | Contenido |
|---|---|
| Operaciones | Todas las compraventas del año |
| Ganancias y Pérdidas | Pares FIFO con PnL neto por operación |
| Resumen Fiscal | Totales e impuesto estimado |
| Instrucciones | Cómo rellenar el Modelo 100 (casilla 0389) |

> **Nota DAC8:** desde 2026 los exchanges están obligados a reportar automáticamente
> las operaciones a la AEAT. Este informe sirve para verificar los datos y rellenar
> la declaración con seguridad.

> **Aviso legal:** este informe es orientativo. Consulta con un asesor fiscal
> para tu declaración. Los tipos son los vigentes en 2026.

---

## 10. Backtesting

Prueba cualquier estrategia sobre datos históricos reales de OKX antes de arriesgar dinero.

```bash
# Grid en BTC-USDT durante 2024
python main.py backtest \
  --strategy grid \
  --symbol BTC-USDT \
  --from 2024-01-01 \
  --to 2024-12-31 \
  --balance 10000

# DCA en ETH-USDT con configuración personalizada
python main.py backtest \
  --strategy dca \
  --symbol ETH-USDT \
  --from 2024-06-01 \
  --to 2024-12-31 \
  --config '{"base_order_size":"200","take_profit_pct":"2.0","price_deviation_pct":"3.0"}'
```

El backtest muestra:

| Métrica | Descripción |
|---|---|
| P&L total | Ganancia/pérdida neta en USDT y % |
| Buy & Hold | Qué habría dado simplemente comprar y mantener |
| Win rate | % de trades ganadores |
| Profit Factor | Ganancia bruta / pérdida bruta (>1.5 es bueno) |
| Max Drawdown | Caída máxima desde el pico |
| Sharpe Ratio | Rentabilidad ajustada al riesgo (>1.0 es aceptable) |

---

## 11. Estructura del proyecto

```
okx_trader/
├── main.py              # CLI principal (typer)
├── config/
│   └── settings.py      # Variables de entorno y validación
├── core/
│   ├── exchange.py      # Cliente OKX (paper + live)
│   ├── database.py      # Modelos SQLAlchemy (SQLite)
│   ├── risk_manager.py  # Control de riesgo global
│   └── backtest.py      # Motor de backtesting
├── strategies/
│   ├── grid_bot.py      # Grid Trading
│   ├── dca_bot.py       # Dollar Cost Averaging
│   ├── mean_reversion.py# Mean Reversion con BB + RSI
│   └── signal_follower.py# Copytrading (webhook / Telegram)
├── reporting/
│   ├── fiscal_report.py # Informe IRPF (Excel + JSON)
│   ├── dashboard.py     # Dashboard rich en terminal
│   └── trade_logger.py  # Registro de operaciones
├── data/
│   ├── market_data.py   # Caché OHLCV
│   └── indicators.py    # BB, RSI, volumen
├── execution/
│   ├── order_manager.py # Seguimiento de órdenes
│   └── position_tracker.py # Estado de posiciones
├── tests/               # Suite de tests (114 tests)
├── logs/                # Logs rotativos diarios
├── reports/             # Informes fiscales generados
└── trading.db           # Base de datos SQLite
```

---

## Tests

```bash
# Ejecutar todos los tests
python -m pytest

# Con detalle
python -m pytest -v

# Solo un módulo
python -m pytest tests/test_fiscal_report.py -v
```

La suite cubre: settings, database, exchange (paper mode), grid bot,
DCA bot, risk manager y cálculo FIFO/IRPF.
