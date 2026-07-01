# SESSION.md — Estado del proyecto (HOT — se carga en cada sesion via @SESSION.md)

Complemento de CLAUDE.md. **Este archivo es deliberadamente corto** para no gastar tokens en
cada arranque. El detalle historico completo (logs de sesion, tablas de backtests, referencia de
cada modulo) vive en **`SESSION_ARCHIVE.md`** — leelo SOLO cuando lo necesites, no por defecto.

**Ultima actualizacion: 2026-07-01 (sesion 13)**

Punteros a referencia (leer bajo demanda, NO precargar):
- `SESSION_ARCHIVE.md` — logs sesiones 12/13, auditoria 2026-06-30, resultados backtest, referencia
  detallada de Pro Trend v12/v13, macro/market/funding context, indicadores, bugs resueltos.
- `backtests/STRATEGY_VERSIONS.md` — historial de versiones de estrategia.
- `SWING_PLAN.md` — diseno y criterios go/no-go del Swing Allocator.
- Journals: NO hacer `Read` del JSON crudo (pueden ser >10 MB). Usar
  `python tools/journal_summary.py <ruta>` o `/journal-summary`.

---

## ESTADO ACTUAL

**Pro Trend v13** (en codigo). Framework de validacion COMPLETADO. Siguiente: paper trading 6 meses.
- 2018-2026 realistic: +521.84% / CAGR +25.7% (partial_exit=150%) vs B&H +550% / +26.4%.
- 2015-2026 realistic: +5812% / CAGR +44.9% — 3 ciclos bull validados.
- Ventaja real: riesgo, no retorno. 35% tiempo en mercado, evita crashes -70%.

**Swing Allocator v3 ADOPTADO como default** (2026-07-01). Validacion 100% COMPLETADA. Lista para operar.
- Config default: `use_regime=True`, `use_halving=True`, `regime_off_on_bear_onset=True`,
  `bull_peak_ema50_cap_enabled=True`, `bull_peak_ema50_cap=0.85`, resto False.
- 2015-2026 realistic: $6.998M, CAGR +81.39%, PF 6.10, Max DD -53.64%, `btc_vs_bnh_ratio=0.8531`.
- 2018-2026 realistic: $174.8k, CAGR +42.99%, PF 5.55, Max DD -53.42%, `btc_vs_bnh_ratio=0.9140`.
- 2015-2026 conservative: $6.806M, CAGR +80.93%, PF 5.84, Max DD -53.69%, `btc_vs_bnh_ratio=0.8301`.
- Rollback: `--config '{"bull_peak_ema50_cap_enabled": false}'` (→v2), `{"regime_off_on_bear_onset": false}'` (→v1).

**Proximo foco Swing:** auditar eventos `bull_peak_ema50_cap_*` por ciclo antes de anadir otro flag;
reducir Max DD sin romper BTC acumulado. (Detalle y candidatas descartadas: SESSION_ARCHIVE.md.)

---

## REGLAS INVARIANTES ANTES DE TOCAR CODIGO

Prioridad sobre cualquier optimizacion. Un cambio que no las cumpla NO pasa a default aunque mejore
un backtest puntual.

### 1. Lookahead bias — tolerancia cero
- Dato diario/semanal/4H usado intradia debe estar CERRADO antes del tick. No usar vela/semana/bloque
  4H en curso.
- Externos con offset conservador: MVRV/CoinMetrics = dia anterior; DXY/NDX/VIX/Yahoo = sesion anterior;
  Funding OKX = dia completo anterior.
- Indicador nuevo: documentar en codigo que timestamp representa y por que no mira futuro. Ante duda,
  asumir que el dato NO estaba disponible y desplazarlo.

### 2. Overfitting — protocolo obligatorio
- No promover un cambio que solo mejora 2018-2026 o que elimina un unico trade perdedor.
- Ventana principal BTC: **2015-01-01 a 2026-01-01** (mas trades, 3 ciclos). 2018-2026 = secundaria.
- Comparar candidatos por **CAGR y Max DD** (anclas estables); PF como rango, NO como ancla (es fragil
  al punto de inicio — ver sesion 13). Fijar siempre inicio 2015.
- Cada cambio se testea AISLADO contra baseline y luego combinado solo si aporta por separado.
- Coste minimo `--costs realistic`; candidatos finales tambien `conservative`.
- Threshold nuevo necesita justificacion ESTRUCTURAL, no "porque arregla T6/T8/T9".
- Si sube CAGR pero empeora mucho PF/MaxDD → variante agresiva, no default.

### 3. Preservar rollbacks
- No sobrescribir ni borrar journals existentes. Todo cambio nuevo debe ser reversible por config.
- Rollback conceptual Pro Trend v13: `partial_exit_pct=150.0`, `partial_exit_size=0.33`,
  `entry_score_min=9`, `adx_min_entry=15.0`, `trailing_stop_pct=0.22`, `trailing_stop_pct_bull=0.28`,
  `cooldown_atr_stop_days=30`, `macd_exit_enabled=False`, `allow_shorts=False`,
  `disable_external_filters=False`.
- Swing v1/v2 config exactas: ver "SWING ALLOCATOR — REFERENCIA" en SESSION_ARCHIVE.md.

### 4. Determinismo de datos
- Backtests deterministas via cache OHLCV (`data/cache/`). Runs con rango cacheado = velas identicas.
- Resultado SENSIBLE al punto de inicio (dataset canonico v1: 96906 velas). No mezclar caches entre maquinas.
- Backtests CONTINUOS — nunca reiniciar balance en frontera de año/mes.

---

## SIGUIENTE PASO OBLIGATORIO — Pro Trend

Paper trading MANDATORIO min 6 meses, sizing 50%, antes de capital real:
```bash
python main.py start --strategy pro --symbol BTC-USDT --config '{"size_ultra": 0.45, "size_high": 0.40, "size_mid": 0.30}'
```
Monitorear: entries <3/mes, losses >20%, cooldown activo. (`start` requiere confirmacion explicita.)

---

## PENDIENTES ABIERTOS

- **Q4 2025 (Swing):** ping-pong estructural residual. Via viva: cap-target con `bear_onset` activo.
  Descartados: cooldown=7d, ADX gate. Detalle en SESSION_ARCHIVE.md ("Q4 2025 mitigacion").
- **Max DD Swing (-55%):** viene de estar 90-100% BTC en TECHOS de ciclo, no de los bears.
  Caps globales de `max_btc_pct` descartados (destruyen CAGR). v3 ataca el techo quirurgicamente.
- **Pro Trend bugfixes candidatos** (P1, sin backtest aislado aun): fix MACD 4H key,
  fix VIX sizing cap (ya en codigo, pendiente validar). Ver auditoria en SESSION_ARCHIVE.md.

---

## DONDE ESTA CADA COSA (referencia rapida, sin abrir el archivo)

- Estrategias: `strategies/pro_trend.py`, `strategies/swing_allocator.py`, `strategies/adaptive_trend.py`,
  `strategies/scalp_momentum.py`. Indicadores: `strategies/indicators.py` (UNICO activo).
- Contexto externo: `strategies/macro_context.py` (MVRV+halving), `strategies/market_context.py`
  (DXY/NDX/VIX), `strategies/funding_context.py`.
- Backtest: `core/backtest.py`. Cache: `data/ohlcv_cache.py`. Journals: `reporting/trade_journal.py`,
  `reporting/swing_journal.py`.
- Umbrales y config detallada de cada modulo: SESSION_ARCHIVE.md.
