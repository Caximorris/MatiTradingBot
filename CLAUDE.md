# MatiTradingBot — CLAUDE.md

Bot de trading automatizado para OKX. Python 3.12+. Windows 10, PowerShell.
Leer este archivo Y `SESSION.md` antes de tocar cualquier archivo.
`SESSION.md` es corto (estado vivo + reglas invariantes). El detalle historico completo esta en
`SESSION_ARCHIVE.md` — leerlo SOLO bajo demanda, no por defecto (ahorro de tokens).

---

## ESTILO Y CONVENCIONES (heredadas — el plugin ECC esta DESACTIVADO en este proyecto)

> ECC (`ecc@ecc`) esta puesto a `false` en `.claude/settings.local.json` para ahorrar tokens (no
> inyecta su catalogo de ~300 skills cada turno). Se pierden los skills `ecc:*` y las reglas globales.
> Estas son las reglas que SI se aplican aqui, re-declaradas para no perder comportamiento:

- **Modo advisor (comunicacion):** No eres mi asistente, eres mi asesor. (1) No empieces nunca con
  validacion — la primera frase desafia mi supuesto o expone un hueco. (2) Califica confianza:
  [Certain]/[Likely]/[Guessing]. (3) Prohibidas: "Great question", "You're absolutely right",
  "tiene mucho sentido", "Absolutamente". (4) Discrepa con estructura: "Discrepo porque X. Haria Y.
  El riesgo de tu enfoque es Z". (5) La respuesta incomoda primero, en la linea 1. (6) Sin parrafos
  de calentamiento. (7) Si insisto sin dato nuevo, manten tu posicion.
- **Git:** commits `<type>: <desc>` (feat/fix/refactor/docs/test/chore/perf/ci). SIN atribucion
  Co-Authored-By. Commit/push SOLO cuando lo pida.
- **Eficiencia de tokens:** hacer lo util con el minimo de tokens/llamadas. Lecturas dirigidas
  (offset/limit, Grep) sobre archivos enteros; editar en vez de reescribir; batch de llamadas
  independientes en un turno.
- **Autonomia:** ejecutar skills/backtests directo sin preguntar. Excepciones que SIEMPRE requieren
  OK explicito: modo live/paper (`start`), operaciones git, y tocar `pro_trend.py` (congelado).
- Resto (KISS/DRY/YAGNI, tests, seguridad): sentido comun del oficio, sin ceremonia.

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
- Backtests DETERMINISTAS (desde 2026-07-01): `fetch_historical_bars` cachea OHLCV en
  `data/cache/{symbol}_{bar}.json` (gitignored). Runs con rango cubierto se sirven del cache
  sin red → velas identicas. Para forzar re-descarga: borrar el archivo del cache.
  DATASET CANONICO (2026-07-02): `BTC-USDT_1H` = 102931 filas (2014-04-25 → 2026-01-01, continuo,
  cero huecos >24h, gap-fill Bitstamp completo). Reemplaza al viejo de 96906 velas. Ventana
  2015-2026 = 96930 velas analizadas tras warmup.
  NOTA (2026-07-06, hallazgo de `data-audit`): de esas 102931 filas, **474 son timestamps
  duplicados** (idéntico OHLCV, 0 conflictos de valor) agrupados en el empalme Bitstamp→OKX de
  2017 → **102457 distintas**. Es redundancia benigna (no altera ningún valor de backtest) pero
  el conteo "102931" está inflado. NO deduplicar durante el forward-test: sería una mutación del
  cache canónico prohibida (contrato §4/§6c) y movería la paridad. Revisar solo tras cerrar el
  paper, vía cambio versionado en git.
  El resultado es SENSIBLE al punto de inicio del histórico (leccion historica: 97105 velas de
  relleno PARCIAL daban PF 2.40 vs 96906 → PF 4.33; el 102931 continuo da PF 4.43): el cache da
  reproducibilidad, no corrección. PF es fragil al arranque — usar CAGR y Max DD como anclas. No
  mezclar caches entre maquinas.
  NOTA (2026-07-06): el cache OHLCV `data/cache/BTC-USDT_1H.json` esta VERSIONADO en git (no es
  gitignored) — git es el backup del dataset canonico. Un prefetch de `tools/strategy_audit.py` lo
  extendio a 104932 velas al pedir warmup antes del inicio canonico; se RESTAURO con
  `git checkout HEAD -- data/cache/BTC-USDT_1H.json` (vuelve a 102931). El ancla v5 reproducia identica
  ($9,164,157.14) incluso con el cache extendido — el conteo "velas analizadas" no es ancla. Las
  herramientas de reporte (`backtest_report.py`, `strategy_audit.py`) ahora CLAMPAN al rango del cache
  (`report_common.cache_bounds`) y NO re-descargan, para no volver a mutarlo.
- Maximo 800 lineas por archivo
- `transient=True` en Rich Progress. Evitar Unicode en Windows (cp1252)
- EFICIENCIA DE TOKENS: NUNCA hacer `Read` de un journal crudo (`backtests/journal_*.json`, hasta
  ~10 MB). Un hook (`.claude/hooks/read_guard.py`) lo bloquea. Usar `/journal-summary` o
  `python tools/journal_summary.py <ruta>`. El mismo hook bloquea cualquier `Read` de archivos >150 KB;
  para esos, leer un slice (offset/limit) o usar `Grep`.

---

## REGLAS DE COMPORTAMIENTO

1. **Backtests: SI ejecutar** (cambio 2026-07-01). Se pueden correr hasta 5 en paralelo, en background. SIEMPRE mostrar los resultados al terminar. Live/paper (`start`) sigue requiriendo confirmacion.

2. **Pro Trend PAUSADO INDEFINIDAMENTE** (decision 2026-07-01, sesion 14). No se continua paper
   trading ni optimizacion. NO tocar sus parametros — el codigo queda CONGELADO en v13
   (partial_exit_pct=150.0). Framework de validacion estaba completo (baselines, ETH, sensitivity,
   MAE/MFE/R, partial_exit, BTC 2015-2026). Foco 100% en Swing Allocator. Retomable en el futuro.

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

15. **Swing Allocator v2 adoptado como default** (2026-07-01, sesion 13).
    Config: `use_regime=True, use_halving=True`, todo lo demas False.
    `delta_post_halving=0.20, delta_bear_onset=-0.20` + **`regime_off_on_bear_onset=True`** (v2).
    v2 suprime SOLO la rama regime_bull cuando bear_onset esta activo (mantiene regime_bear):
    arregla el ping-pong de Q4 2025 y mejora AMBAS anclas en las dos ventanas.
    2015-26: +80.6% CAGR / Max DD -55.23% (vs v1 78.4% / -57.60%). 2018-26: +41.5% / -53.42%.
    WF v2 4/4 TEST positivo ✅ | ETH identico a v1 (sin halvings, el flag nunca dispara) ✅.
    Reversible: `--config '{"regime_off_on_bear_onset": false}'` vuelve a v1.
    MVRV, Pi Cycle, RSI, VIX, MACD 4H: descartados definitivamente (use_* = False en defaults).
    Siguiente: investigar reduccion de Max DD (cap max_btc_pct en bull_peak / vol-targeting). Ver SESSION.md.

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

# Observabilidad del forward-test paper (read-only, no toca la estrategia — plan T4/T6/T7/T13)
python main.py paper-status [--watch 30]   # control center de v5/v6/legacy
python main.py anomaly-check [--telegram]  # red-flags de infra/datos/estado (dedup)
python main.py forward-report [--json|--out F|--telegram]  # solo datos post-inicio forward-test
python main.py data-audit [--live]         # integridad del cache OHLCV (nunca re-descarga)
```

---

## ARQUITECTURA BACKTEST (resumen)

`BacktestClient` imita `OKXClient` al 100% — estrategias sin cambios de codigo.
Warmup: Pro Trend 380 dias, Adaptive 240 dias, Scalp 25 dias.
`equity_curve: list[tuple[datetime, Decimal]]` — timestamps UTC reales.
Journal automatico: `backtests/journal_{estrategia}_{simbolo}_{timeframe}_{ts}.json`

---

@SESSION.md
