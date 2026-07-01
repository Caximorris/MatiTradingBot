---
description: Ejecutar el backtest reproducible estandar (datos cacheados, costes realistic)
argument-hint: [--config '{...}'] [ventana: 2015|2018]
---

Ejecuta el backtest CANONICO reproducible. Args: $ARGUMENTS

Reglas:
- **Ventana principal por defecto: BTC 2015-2026** (mas trades, 3 ciclos bull). 2018-2026 es
  secundaria (comparacion vs B&H reciente). Si el arg dice "2018", usa esa.
- **Siempre `--costs realistic`** (0.1% fee + 5bps slippage) salvo que se pida otra cosa.
  Para candidatos finales mirar tambien `conservative`.
- **Datos deterministas:** el cache OHLCV (`data/cache/`) garantiza velas identicas entre runs.
  Si el conteo de velas cambia entre dos runs de la misma ventana, PARA — el cache esta roto.
- Puedes ejecutarlo tu (hasta 5 en paralelo, background). Muestra SIEMPRE los resultados.

Comandos base (PowerShell; JSON escapado con `\"`):
```
python main.py backtest --strategy swing --from 2015-01-01 --to 2026-01-01 --costs realistic
python main.py backtest --strategy swing --from 2018-01-01 --to 2026-01-01 --costs realistic
```
Con hipotesis: anade `--config "{\"param\":valor}"`.

Al acabar, reporta: velas analizadas, CAGR, PF, Max DD, trades, y el desglose Q4 2025 si aplica.
No interpretes en solitario — pasa a /compare-results contra el baseline.
