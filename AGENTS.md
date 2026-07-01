# MatiTradingBot — AGENTS.md

Bot de trading automatizado para OKX. Python 3.12+. Windows 10, PowerShell.
Leer este archivo Y `SESSION.md` antes de tocar cualquier archivo.

---

## STACK Y ESTRUCTURA

**No usar `requests`** — usar `urllib.request` (HTTP sincrono) o `aiohttp` (async).

Directorio raiz: `C:\Users\Matias\Documents\Mati\matiproyects\MatiTradingBot\`

Archivos clave:
- `main.py` — CLI typer (todos los comandos)
- `core/backtest.py` — BacktestClient + BacktestEngine
- `strategies/pro_trend.py` — estrategia principal
- `strategies/swing_allocator.py` — Swing Allocator v2 DEFAULT actual
- `strategies/indicators.py` — UNICO modulo de indicadores activo (`data/indicators.py` es el antiguo, ignorar)
- `strategies/macro_context.py` — MVRV + halving (CoinMetrics API)
- `strategies/market_context.py` — DXY + NASDAQ + VIX (Yahoo Finance)
- `strategies/funding_context.py` — funding rate historico OKX
- `reporting/swing_journal.py` — journal de rebalanceos Swing
- `SWING_PLAN.md` — diseno y validacion Swing
- `backtests/STRATEGY_VERSIONS.md` — registro de versiones y descartes

Archivos eliminados (no buscar): `strategies/mean_reversion.py`, `strategies/signal_follower.py`

---

## CONVENCIONES CRITICAS

- Importes monetarios: `Decimal`, NUNCA `float`
- Fechas en DB: UTC siempre. Conversion a Europe/Madrid SOLO en reporting
- Paper mode por defecto. `TRADING_MODE=live` requiere confirmacion explicita
- Logs con `loguru`. Nunca `print()` para logs
- `OrderResult` siempre requiere `size` y `limit_price` — no omitir (errores silenciosos)
- Backtests CONTINUOS — nunca reiniciar balance en frontera de año/mes
- Backtests DETERMINISTAS: `data/cache/{symbol}_{bar}.json` cachea OHLCV. Misma ventana debe dar mismo conteo de velas.
- Maximo 800 lineas por archivo
- `transient=True` en Rich Progress. Evitar Unicode en Windows (cp1252)

---

## REGLAS DE COMPORTAMIENTO

1. **Backtests: SI ejecutar automaticamente** si el usuario pide analizar/validar estrategia.
   Maximo 5 en paralelo, siempre reportar resultados. Live/paper (`python main.py start ...`) requiere confirmacion explicita.

2. **No tocar parametros de Pro Trend** hasta completar paper trading 6 meses. Foco actual: Swing Allocator.

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

11. **Codex skill persistente**: para tareas de Swing, usar `mati-swing-validator`.
    La copia versionada esta en `.codex/skills/mati-swing-validator/` y la copia instalada en `C:\Users\Matias\.codex\skills\mati-swing-validator\`.

12. **Swing Allocator v3 es default actual**:
    - `regime_off_on_bear_onset=True`
    - `bull_peak_ema50_cap_enabled=True`, `bull_peak_ema50_cap=0.85`
    - `use_regime=True`, `use_halving=True`, resto False
    - `delta_post_halving=0.20`, `delta_bear_onset=-0.20`
    - `base_btc_pct=0.60`, `min_btc_pct=0.30`, `max_btc_pct=1.00`
    - v2 suprime SOLO `regime_bull` durante `bear_onset`; mantiene `regime_bear`.
    - v3 capea target a 85% en `bull_peak` solo si BTC pierde la EMA50D del dia anterior cerrado.
    - Rollback v2: `--config '{"bull_peak_ema50_cap_enabled": false}'`
    - Rollback v1: `--config '{"regime_off_on_bear_onset": false}'`

13. **Protocolo de comparacion Swing**:
    - Baseline v3 anclado BTC 2015-2026 realistic: $6.998M, CAGR +81.39%, Max DD -53.64%, PF 6.10, `btc_vs_bnh_ratio=0.8531`.
    - BTC 2018-2026 realistic v3: $174.8k, CAGR +42.99%, Max DD -53.42%, PF 5.55, `btc_vs_bnh_ratio=0.9140`.
    - BTC 2015-2026 conservative v3: $6.806M, CAGR +80.93%, Max DD -53.69%, PF 5.84, `btc_vs_bnh_ratio=0.8301`.
    - Anclas: CAGR y Max DD. PF es fragil al punto de inicio; usarlo como rango, no como veredicto unico.
    - Siempre comprobar mismo dataset/conteo de velas, misma ventana y mismos costes.
    - Reportar tambien `final_btc_qty`, `bnh_initial_btc` y `btc_vs_bnh_ratio`; para un holder BTC, mas USDT con menos BTC no es automaticamente mejor.
    - No adoptar defaults si solo mejora 2015-2026. Validar tambien 2018-2026 y candidato final en conservative.

14. **Estado siguiente Swing (2026-07-01)**:
    - Capar `max_btc_pct` global a 0.90/0.80/0.70: DESCARTADO; mata CAGR.
    - Todo-o-nada: DESCARTADO; empeora vs v2.
    - `min_btc_pct=0.0`: NO perseguir como default. Mejora CAGR/DD en USDT, pero reduce mucho BTC final (`btc_vs_bnh_ratio` ~0.50-0.54 vs v2 0.843). Decision del usuario: mantener una sola estrategia y afinar v2, no dividir perfiles.
    - Late-cycle cap `bull_peak_ema50_cap=0.85`: ADOPTADO como v3. Mejora CAGR/DD y mantiene BTC acumulado por encima de v2, pero Q4 2025 empeora vs v2 (+$290k -> -$42.6k). Vigilar que no sea solo redistribucion entre ciclos.
    - Proximo foco: no anadir mas flags. Auditar eventos `bull_peak_ema50_cap_*` y comparar v3 vs v2 por ciclo antes de tocar otro parametro.

15. **`adx_min_entry` en ProTrendConfig**: existe en el dataclass y en el gate (_g_adx_min),
    y ahora esta correctamente en `from_dict()` y `to_dict()`. Bug corregido 2026-06-29.
    Las variantes ADX del sensitivity del 2026-06-28 son invalidas (corrieron todas con 15.0).
    Re-correr antes de sacar conclusiones sobre el gate ADX.

16. **Al crear nuevos indicadores**, añadirlos a `strategies/indicators.py`.

17. **Windows + PowerShell**: sintaxis PS. Para POSIX usar Bash tool.

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
