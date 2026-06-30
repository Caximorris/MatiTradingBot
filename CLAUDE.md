# MatiTradingBot — CLAUDE.md

Bot de trading automatizado para OKX. Python 3.12+. Windows 10, PowerShell.
Leer este archivo Y `SESSION.md` antes de tocar cualquier archivo.

---

## STACK Y ESTRUCTURA

**No usar `requests`** — usar `urllib.request` (HTTP sincrono) o `aiohttp` (async).

Directorio raiz: `C:\Users\Matias\Documents\Mati\matiproyects\MatiTradingBot\`

Archivos clave:
- `main.py` — CLI typer (todos los comandos)
- `core/backtest.py` — BacktestClient + BacktestEngine
- `strategies/pro_trend.py` — estrategia principal (NO modificar hasta completar paper trading)
- `strategies/swing_allocator.py` — Swing Allocator v1 (regimen+halving, delta_halving=±0.20). NO tocar pro_trend.py
- `strategies/indicators.py` — UNICO modulo de indicadores activo (`data/indicators.py` es el antiguo, ignorar)
- `strategies/macro_context.py` — MVRV + halving (CoinMetrics API)
- `strategies/market_context.py` — DXY + NASDAQ + VIX (Yahoo Finance)
- `strategies/funding_context.py` — funding rate historico OKX
- `reporting/swing_journal.py` — journal de rebalanceos (Swing Allocator)
- `SWING_PLAN.md` — diseño completo y plan de validacion del Swing Allocator

Archivos eliminados (no buscar): `strategies/mean_reversion.py`, `strategies/signal_follower.py`

---

## CONVENCIONES CRITICAS

- Importes monetarios: `Decimal`, NUNCA `float`
- Fechas en DB: UTC siempre. Conversion a Europe/Madrid SOLO en reporting
- Paper mode por defecto. `TRADING_MODE=live` requiere confirmacion explicita
- Logs con `loguru`. Nunca `print()` para logs
- `OrderResult` siempre requiere `size` y `limit_price` — no omitir (errores silenciosos)
- Backtests CONTINUOS — nunca reiniciar balance en frontera de año/mes
- Maximo 800 lineas por archivo
- `transient=True` en Rich Progress. Evitar Unicode en Windows (cp1252)

---

## REGLAS DE COMPORTAMIENTO

1. **No ejecutar `python main.py ...` automaticamente.** Mostrar el comando exacto y dejar que el usuario lo corra.

2. **No tocar parametros de Pro Trend** hasta completar paper trading 6 meses. Todo el framework de validacion completado (baselines, ETH, sensitivity, MAE/MFE/R, partial_exit, BTC 2015-2026). Version actual: v13 con partial_exit_pct=150.0 por defecto. Siguiente: paper trading.

3. **Lookahead fixes aplicados — no revertir:**
   - `macro_context._lookup`: offset empieza en 1 (MVRV = dia anterior)
   - `market_context._spot/_pct`: delta empieza en 1 (VIX/DXY/NDX = sesion anterior)
   - `pro_trend._build_4h_context`: excluye bloque 4H actual incompleto
   - `funding_context.get_funding_rate_at`: delta empieza en 1 (dia completo anterior)
   - `backtest._fill_market`: usa `self._fee_rate` y `self._slippage_bps` (configurable)

4. **MACD exit DESACTIVADO** (`macd_exit_enabled=False`). No reactivar sin justificacion backtest.

5. **allow_shorts=False** por defecto. Para activar: `{"allow_shorts": true}`.

6. **ScalpMomentum se corre en 1H** (no 15m): `--timeframe 1H`

7. **Cooldown Pro Trend es DATE-BASED** (`_cooldown_until: "YYYY-MM-DD"`). ScalpMomentum es de barras.

8. **`disable_external_filters=True`** en ProTrendConfig desactiva MVRV/VIX/DXY/NDX/funding/Pi Cycle. Solo para ablation tests, nunca en produccion.

9. **Costes en backtest:**
   - `--costs ideal` = 0.1% fee, 0 slippage (defecto)
   - `--costs realistic` = 0.1% fee + 5bps slippage
   - `--costs conservative` = 0.1% fee + 15bps slippage

10. **walk-forward y baselines** corren 8 y 5 sub-backtests respectivamente. ~40-60 min total. Normal.

13. **`adx_min_entry` en ProTrendConfig**: en `from_dict()` y `to_dict()`. Bug corregido 2026-06-29.
    Sensitivity ADX re-corrido y confirmado: adx=15 es correcto.

14. **`partial_exit_pct=150.0` es el default desde v13** (2026-06-30). Vende 33% de la posicion
    cuando la ganancia supera 150%. Confirmado por backtest: +1pp CAGR, mejor PF, DD neutro.
    Para desactivar: `--config '{"partial_exit_pct": 0.0}'`.

15. **Swing Allocator v1 adoptado como default** (2026-06-30).
    Config: `use_regime=True, use_halving=True`, todo lo demas False.
    `delta_post_halving=0.20, delta_bear_onset=-0.20` — ya en SwingAllocatorConfig por defecto.
    WF v1 4/4 ✅ | ETH +56.4% CAGR ✅ | Sensitivity 15 variantes ✅ | 2015-2026 +77.4% CAGR.
    MVRV, Pi Cycle, RSI, VIX, MACD 4H: descartados definitivamente (use_* = False en defaults).
    Siguiente: tests segunda ronda (threshold=0.15, deltas asimetricos, ETH re-validacion v1). Ver SESSION.md paso 8.

11. **Al crear nuevos indicadores**, añadirlos a `strategies/indicators.py`.

12. **Windows + PowerShell**: sintaxis PS. Para POSIX usar Bash tool.

---

## COMANDOS PRINCIPALES

```bash
python main.py backtest --strategy pro --from 2018-01-01 --to 2026-01-01 --costs realistic
python main.py walk-forward --strategy pro --costs realistic
python main.py baselines --from 2018-01-01 --to 2026-01-01 --costs realistic
python main.py backtest --strategy scalp --from 2022-01-01 --to 2026-06-01 --timeframe 1H
python main.py start --strategy pro --symbol BTC-USDT
python main.py compare --strategies "adaptive,pro" --from 2018 --to 2026
```

---

## ARQUITECTURA BACKTEST (resumen)

`BacktestClient` imita `OKXClient` al 100% — estrategias sin cambios de codigo.
Warmup: Pro Trend 380 dias, Adaptive 240 dias, Scalp 25 dias.
`equity_curve: list[tuple[datetime, Decimal]]` — timestamps UTC reales.
Journal automatico: `backtests/journal_{estrategia}_{simbolo}_{timeframe}_{ts}.json`

---

@SESSION.md
