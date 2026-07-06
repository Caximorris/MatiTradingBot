# SESSION_ARCHIVE.md — Historial completo y referencia detallada

> ARCHIVO HISTORICO. NO se carga en cada sesion (a diferencia de SESSION.md). Contiene logs de
> sesion, tablas de backtest, auditorias y referencia por modulo. Leelo BAJO DEMANDA cuando
> necesites un dato concreto; el estado vivo y las reglas invariantes estan en `SESSION.md`.
> Snapshot tomado 2026-07-01 (sesion 13).

**Ultima actualizacion: 2026-07-01 (sesion 13)**

---

## SESION 13 (2026-07-01) — SWING v3 ADOPTADO + Q4 2025 RESUELTO + DD reducido

**Fragilidad del punto de inicio — RESUELTA.** Medido v1 con inicio 2015/2016/2017 (datos cacheados):
CAGR robusto (78.4/81.2/78.0%), Max DD robusto (-57.6/-57.2/-58.7%), pero PF fragil (4.33/2.51/3.70).
El "PF 4.33" es propiedad de EMPEZAR EN 2015, no de la estrategia. Los pocos trades monstruo lo dominan.
REGLA nueva: comparar candidatos por CAGR y Max DD (anclas estables), PF como rango, fijar inicio 2015.
El susto "2.40" (sesion 12) era el extremo de esta sensibilidad, no un bug.

**Swing Allocator v2 ADOPTADO como default** — `regime_off_on_bear_onset=True`. Suprime SOLO la rama
`regime_bull` cuando `bear_onset` activo (mantiene `regime_bear`). Arregla el ping-pong de Q4 2025 y
mejora AMBAS anclas en las dos ventanas:
- 2015-26: +80.6% CAGR / Max DD -55.23% (v1: 78.4% / -57.60%). Q4 2025: -$130k → **+$290k**.
- 2018-26: +41.5% CAGR / Max DD -53.42% (v1: 36.7% / -58.11%).
- WF 4/4 TEST positivo, >= v1 en las 4 ventanas. ETH identico a v1 (sin halvings).
Razon estructural: `bear_onset` = distribucion post-halving; perseguir breakouts alcistas ahi es trampa
en los 3 ciclos. Reversible con `--config '{"regime_off_on_bear_onset": false}'` (vuelve a v1).
DESCARTADO: suprimir TODO el regime (no solo bull) — rompio 2022, Q1 2023 -$274k. Ver STRATEGY_VERSIONS.

**Max DD diagnosticado (pendiente de atacar).** El DD -55% NO viene de los bears (ahi ya esta en floor
30%) sino de estar 90-100% BTC en TECHOS de ciclo. Evidencia: mayo 2021 al 100% BTC, de-risk tardio
(vendio a -36% del top porque el cruce EMA es lagging). Causa: `halving_bull_peak`+`regime_bull` apilan
a max_btc_pct=1.00 en euforia. Fix candidato: capar max_btc_pct en bull_peak o vol-targeting.
ADVERTENCIA: DD y CAGR acoplados — capar el techo quita captura del final del bull. Medir, no asumir.
NOTA: "reabrir en el minimo" descartado — imposible sin retrospectiva.

**Bateria DD/exposicion post-v2 completada.** Capar `max_btc_pct` global a 0.90/0.80/0.70
queda DESCARTADO: baja exposicion pero destruye CAGR ($4.08M/$3.68M/$1.83M vs v2 $6.69M).
Todo-o-nada tambien DESCARTADO ($5.58M y 0 BTC final). `min_btc_pct=0.0` pasa las anclas USDT/DD:
2015 realistic $7.56M, CAGR +82.66%, Max DD -53.41%, PF 4.78; 2018 realistic $186k,
CAGR +44.14%, Max DD -53.42%; 2015 conservative $7.36M, CAGR +82.24%, Max DD -53.47%.
Pero reduce `btc_vs_bnh_ratio` a ~0.50-0.54 vs v2 0.843x. Decision: NO dividir en perfiles
ni perseguirlo como default; mantener v2 y afinar la estrategia unica. Siguiente foco: cambios
quirurgicos sobre v2 que reduzcan DD sin romper BTC acumulado.

**Swing Allocator v3 ADOPTADO como default** — v2 + `bull_peak_ema50_cap_enabled=True`,
`bull_peak_ema50_cap=0.85`. Regla quirurgica: durante `bull_peak`, si BTC pierde la EMA50D del
dia anterior cerrado, el target maximo baja a 85%. Mantiene `min_btc_pct=0.30` y evita caps globales.
Validacion:
- 2015-26 realistic: $6.998M, CAGR +81.39%, Max DD -53.64%, PF 6.10, `btc_vs_bnh_ratio=0.8531`.
- 2018-26 realistic: $174.8k, CAGR +42.99%, Max DD -53.42%, PF 5.55, `btc_vs_bnh_ratio=0.9140`.
- 2015-26 conservative: $6.806M, CAGR +80.93%, Max DD -53.69%, PF 5.84, `btc_vs_bnh_ratio=0.8301`.
Trade-off: Q4 2025 empeora vs v2 (+$290k -> -$42.6k en 2015 realistic), pero las anclas completas
CAGR/DD/BTC mejoran en 2015 y 2018, y conservative no invalida. Rollback v2:
`--config '{"bull_peak_ema50_cap_enabled": false}'`. Proximo foco: auditar eventos
`bull_peak_ema50_cap_*` por ciclo antes de anadir otro flag.

**Automatizacion Codex aplicada.** Nueva skill local/versionada `.codex/skills/mati-swing-validator/`
e instalada en `C:\Users\Matias\.codex\skills\mati-swing-validator\` para sesiones nuevas. `AGENTS.md`
actualizado: usar la skill al trabajar Swing, reportar `btc_vs_bnh_ratio`, y tratar `min_btc_pct=0.0`
como no-default por perdida de BTC acumulado. `reporting/swing_journal.py` y `main.py` ahora guardan `meta.resolved_config`
y `meta.backtest` en journals Swing nuevos para no perder Max DD/CAGR/PF.

---

## SESION 12 (2026-07-01) — DETERMINISMO DE DATOS + Q4 2025

**Hallazgo critico: los backtests NO eran reproducibles.** Dos runs de la misma ventana
(BTC 2015-2026) daban conteos de velas distintos (96805 / 96906 / 97105) y por tanto metricas
distintas (PF 2.40 vs 4.33). Causa: `fetch_historical_bars` truncaba la paginacion OKX en
silencio ante cualquier transitorio (una pagina = 300 velas = la diferencia exacta observada).
El gap-fill de Bitstamp amplificaba el desfase moviendo la frontera 2015→inicio-OKX.

**Fix (commit 12f8630):** cache OHLCV en disco (`data/ohlcv_cache.py`) + reintentos 4x con
backoff en la paginacion. Cache-first sirve slices deterministas; no cachea descargas
incompletas. Validado: re-run da 96906 velas / PF 4.33 identico, cache sin reescribir (cero red).

**Baseline v1 ANCLADO (dataset canonico 96906 velas):** PF 4.33, +78.4% CAGR, Max DD -57.60%,
65 trades, Q4 2025 -$129,784. Coincide con el doc — los numeros de v1 eran correctos, venian de
una descarga completa. Journal canonico: `journal_swing_allocator_..._20260701_072040.json`.

**FRAGILIDAD PENDIENTE:** el resultado es sensible al punto de inicio del historico. El run de
97105 velas (mas relleno Bitstamp 2015-16) daba PF 2.40, no 4.33. Parte del edge documentado
podria ser artefacto del arranque. TODO: medir v1 con inicio 2015 vs 2016 vs 2017 sobre datos fijos.

**adx_min_regime — DESCARTADO.** Hipotesis: gate ADX simetrico en ambas ramas regime elimina el
ping-pong Q4 2025. Resultado (adx=20): NO arregla Q4 2025 (sigue 4-6 rebalanceos perdedores) y
SUBE trades (65→103). El ADX oscila alrededor de 20 en lateral igual que el EMA cruzaba — reubica
el ping-pong, no lo elimina. Revertido del codigo. NOTA: el veredicto inicial "PF se derrumba"
era invalido (comparaba contra baseline no reproducible); con datos fijos la candidata es neutra
en top-line pero falla su objetivo (Q4 2025) y ensucia el PF.

**Q4 2025 sigue PENDIENTE.** Proximo intento sobre datos fijos: Opcion 1 (cap-target cuando
`bear_onset` activo, determinista, no depende de umbral oscilante). Ver "Q4 2025 mitigacion" abajo.

**Regla cambiada:** ahora SI se pueden ejecutar backtests (hasta 5 en paralelo, background,
mostrar resultados). Live/paper sigue requiriendo confirmacion.

---

## ESTADO ACTUAL

**Version en codigo: Pro Trend v13** con 5 lookahead fixes, framework de validacion completo y partial_exit_pct=150% por defecto.
**Resultado honesto 2018-2026 realistic: +521.84% CAGR +25.7% (con partial_exit=150%) vs B&H +550% CAGR +26.4%**
**Resultado 2015-2026 realistic: +5812% CAGR +44.9% — validado en 3 ciclos bull (2017, 2021, 2024-25)**
La ventaja real de Pro Trend NO es el retorno absoluto — es el riesgo: 35% tiempo en mercado, evita crashes del -70%.

**Pro Trend v13: framework de validacion COMPLETADO. Siguiente: paper trading 6 meses en paralelo.**

**Swing Allocator v3 ADOPTADO como default** (2026-07-01). Framework de validacion COMPLETADO.
Config default: `use_regime=True`, `use_halving=True`, `regime_off_on_bear_onset=True`,
`bull_peak_ema50_cap_enabled=True`, `bull_peak_ema50_cap=0.85`, resto False.
BTC 2015-2026 realistic: $6.998M, CAGR +81.39%, PF 6.10, Max DD -53.64%, `btc_vs_bnh_ratio=0.8531`.
BTC 2018-2026 realistic: $174.8k, CAGR +42.99%, PF 5.55, Max DD -53.42%, `btc_vs_bnh_ratio=0.9140`.
BTC 2015-2026 conservative: $6.806M, CAGR +80.93%, PF 5.84, Max DD -53.69%, `btc_vs_bnh_ratio=0.8301`.
Rollback v2: `--config '{"bull_peak_ema50_cap_enabled": false}'`.
**Swing Allocator v3: framework de validacion 100% COMPLETADO. Lista para operar.**

---

## REGLAS INVARIANTES ANTES DE TOCAR CODIGO

Estas reglas tienen prioridad sobre cualquier optimizacion. Si un cambio no las cumple, no se
implementa como default aunque mejore un backtest puntual.

### 1. Lookahead bias - tolerancia cero

- Cualquier dato diario/semanal/4H usado en una decision intradia debe estar cerrado antes del tick.
- No usar la vela diaria actual para decidir en 1H si esa vela aun no cerro.
- No usar la semana actual para `weekly_trend_up`; solo semanas completas.
- No usar el bloque 4H actual si esta incompleto.
- Datos externos siempre con offset conservador:
  - MVRV/CoinMetrics: dia anterior completo.
  - DXY/NDX/VIX/Yahoo: sesion anterior completa.
  - Funding OKX: dia completo anterior, no liquidaciones futuras del mismo dia.
- Si se anade un indicador o filtro nuevo, documentar explicitamente en el codigo/doc:
  que timestamp representa, cuando se publica/cierra y por que no mira futuro.
- Si hay duda sobre disponibilidad historica de un dato, asumir que NO estaba disponible y desplazarlo.

### 2. Overfitting - protocolo obligatorio

- No promover a default un cambio que solo mejora 2018-2026 o que elimina un unico trade perdedor.
- La ventana principal de observacion para BTC es **2015-01-01 a 2026-01-01** porque da mas trades
  y cubre 3 ciclos bull. 2018-2026 queda como comparacion secundaria contra B&H reciente.
- Cada cambio se testea aislado contra v13 baseline y luego combinado solo si aporta por separado.
- Coste minimo de validacion: `--costs realistic`. Para candidatos finales, tambien mirar `conservative`.
- Confirmaciones deseables antes de default:
  - BTC 2015-2026 mejora o mantiene retorno/riesgo.
  - BTC 2018-2026 no se rompe.
  - ETH o walk-forward no contradicen brutalmente el edge.
- Thresholds nuevos deben tener justificacion estructural, no "porque arregla T6/T8/T9".
- Si el cambio aumenta CAGR pero empeora mucho PF/MaxDD, queda como variante agresiva, no default.

### 3. Preservar Pro Trend v13 como rollback

No perder la informacion de v13. Antes de cambios que alteren comportamiento:

- Mantener documentada la config v13 exacta en esta sesion y en `backtests/STRATEGY_VERSIONS.md`.
- No sobrescribir ni borrar journals v13 existentes.
- Todo cambio v14 debe poder desactivarse por config o ser facil de revertir.
- Si se cambia un bug candidato que altera trades, guardar resultado baseline v13 limpio antes.
- Rollback conceptual v13:
  - `partial_exit_pct=150.0`
  - `partial_exit_size=0.33`
  - `entry_score_min=9`
  - `adx_min_entry=15.0`
  - `trailing_stop_pct=0.22`
  - `trailing_stop_pct_bull=0.28`
  - `cooldown_atr_stop_days=30`
  - `macd_exit_enabled=False`
  - `allow_shorts=False`
  - `disable_external_filters=False`

### 4. Orden de trabajo tras esta auditoria

1. Primero correr backtests limpios desde 2015 y 2018 con journal corregido.
2. Despues decidir `partial_exit=150` vs `200` con datos nuevos.
3. Solo despues tocar bugfixes candidatos: MACD 4H key y VIX sizing cap, uno por uno.
4. Los experimentos de alpha quedan para despues de P1 y siempre detras de flags/config.

---

## AUDITORIA 2026-06-30 - ROADMAP DE MEJORAS

Objetivo de esta auditoria: maximizar retorno sin romper la tesis original de Pro Trend.
Conclusion principal: Pro Trend v13 no pierde contra B&H por falta de mas indicadores, sino por
estar 65% del tiempo fuera de mercado. La mejora mas prometedora es gestionar mejor exposicion,
profit-lock y medicion antes de tocar thresholds.

### Hallazgos criticos de lectura de codigo/journals

1. **Journal con partial exits subestima PnL por trade.**
   `close.pnl_usdt` solo refleja el cierre final de la posicion restante. En runs con partial exit,
   el PnL real por trade debe calcularse como `close.balance_usdt_after - open.balance_usdt_before`
   o registrando eventos parciales explicitos. Ejemplo v13 2018-2026:
   - `statistics.total_pnl_usdt`: $48,510
   - PnL real por balance: $52,184
   - PF real aproximado: 4.64 vs PF journal 4.41

2. **`partial_exit=150` vs `partial_exit=200` necesita rerun limpio.**
   El resumen previo dice que 150% gana, pero el journal `20260629_153049` muestra balance final
   $64,158 (+541.59%) para 200%, superior al 150% ($62,184, +521.84%) aunque con PF menor.
   No cambiar default todavia: primero corregir/metodologia journal y rerun comparativo.

3. **Gate MACD 4H candidato a bug.**
   En `run()`, `_g_macd_momentum` usa `h4.get("h4_macd_above", True)`, pero `_build_4h_context()`
   devuelve la clave `macd_above`. Resultado probable: si daily MACD esta negativo, el fallback
   `True` puede hacer que el gate MACD xTF no bloquee nunca por 4H. Es bug candidato, no parametro.

4. **Cap de sizing por VIX elevado candidato a bug.**
   `run()` calcula `size_pct` con `vix_elevated`, pero `_open_long()` recalcula sizing sin pasar
   `vix_elevated`. Resultado probable: VIX>22 no capea realmente a `size_mid` aunque el log lo sugiera.
   Esto explica por que el baseline "sin filtros externos" apenas cambia.

5. **Log de funding en backtest esta desfasado.**
   `BacktestClient.get_funding_rate()` ya llama a `funding_context.get_funding_rate_at()`, pero el log
   aun dice que funding retorna 0.0 siempre. Es solo documentacion/log, pero confunde auditorias.

### Orden recomendado de implementacion

**P0 - Medicion/documentacion (no cambia trades):**
1. Corregir estadisticas de journal para partial exits: incluir `true_pnl_usdt`, PF real por balance,
   y/o eventos `partial_exit`. IMPLEMENTADO 2026-06-30; validar con rerun.
2. Actualizar log de funding en `core/backtest.py`. IMPLEMENTADO 2026-06-30.
3. Rerun limpio de v13 2018-2026 y 2015-2026.
4. Rerun limpio de partial exit: 0%, 150%, 200%.

**P1 - Bugfixes candidatos (pueden cambiar trades, testear aislados):**
1. Fix MACD 4H key: usar `h4.get("macd_above", False)` o clave normalizada.
2. Fix VIX sizing cap: pasar `vix_elevated` a `_open_long()` o persistir el contexto de mercado.
   IMPLEMENTADO 2026-06-30 solo en `strategies/pro_trend.py`; no toca Swing Allocator ni
   `market_context.py`. Pendiente backtest aislado contra baseline.
3. Cada fix debe correr solo y combinado, siempre contra v13 baseline.

**P2 - Experimentos de alpha (default desactivado hasta validar):**
1. Profit-lock / break-even despues de MFE +10%, +15%, +20%.
2. Trailing bull grid: 0.28, 0.30, 0.32, 0.34 en 2018-2026 y 2015-2026.
3. ADX como sizing modifier, no como hard gate: ADX<20 reduce size, ADX>=20 normal.
4. MVRV late-bull de-risk: reducir size o activar profit-lock cuando MVRV >= 2.5/3.0, no bloquear ciegamente.
5. Core BTC + Pro Trend overlay: mantener una exposicion base permanente (ver `SWING_PLAN.md`).

### Comandos de test a correr manualmente

No ejecutar automaticamente desde agentes. El usuario los corre.

```bash
# Baseline v13 actual
python main.py backtest --strategy pro --from 2018-01-01 --to 2026-01-01 --costs realistic
python main.py backtest --strategy pro --from 2015-01-01 --to 2026-01-01 --costs realistic

# Partial exit limpio
python main.py backtest --strategy pro --from 2018-01-01 --to 2026-01-01 --costs realistic --config '{"partial_exit_pct": 0.0}'
python main.py backtest --strategy pro --from 2018-01-01 --to 2026-01-01 --costs realistic --config '{"partial_exit_pct": 150.0}'
python main.py backtest --strategy pro --from 2018-01-01 --to 2026-01-01 --costs realistic --config '{"partial_exit_pct": 200.0}'

# Validacion larga del ganador
python main.py backtest --strategy pro --from 2015-01-01 --to 2026-01-01 --costs realistic --config '{"partial_exit_pct": 150.0}'
python main.py backtest --strategy pro --from 2015-01-01 --to 2026-01-01 --costs realistic --config '{"partial_exit_pct": 200.0}'
```

### Criterios de decision

- Un cambio solo pasa a default si mejora o mantiene 2018-2026 y 2015-2026 con `--costs realistic`.
- Si mejora retorno pero empeora PF/MaxDD de forma material, queda como variante agresiva, no default.
- Si solo mejora por eliminar 1 trade perdedor en muestra de 12, tratar como overfitting salvo que 2015-2026,
  ETH o walk-forward lo confirmen.
- Para capital real sigue vigente: paper trading minimo 6 meses, sizing al 50%, no live antes.

---

## PROXIMOS PASOS (orden estricto — no cambiar parametros antes de completarlos)

### 1. Baselines ✅ COMPLETADO (2026-06-26)
Journals: `backtests/journal_pro_trend_btc_usdt_BTCUSDT_1H_202606260{74917,90305,101717,112546}.json`
Conclusiones clave:
- Filtros externos (MVRV/VIX/DXY/funding): practicamente decorativos en 2018-2026. Los mismos 12 trades
  en los mismos momentos. Diferencia: +$1,207 sin externos (VIX>22 no capea sizing). Mantenerlos.
- Scoring (score_min=9 vs 1): NO filtra ningún trade en BTC. Todos ya tenian score>=9. Impacto solo
  en exit timing. score_min=9 gana $3,743 mas que score_min=1.
- Sizing adaptativo: UNICO driver material. Fijo 50%: +$23k. Adaptativo: +$48k. Dobla el resultado.

### 2. ETH backtest ✅ COMPLETADO (2026-06-26)
Journal: `backtests/journal_pro_trend_eth_usdt_ETHUSDT_1H_20260626_074540.json`
Resultado: +370.7%, CAGR +29.4%, PF 1.77, 13 trades (4W/9L), Max DD -42.76%, 30.1% tiempo en mercado
B&H ETH: +2230% (ETH ciclo 2020-2021 fue extremo)
Conclusiones clave:
- La logica funciona en ETH (PF 1.77 > 1.0) — no es overfitting BTC puro. Anti-overfitting confirmado.
- Pero el edge es mas debil: PF 1.77 vs BTC 3.64. Win rate 31% vs BTC 50%.
- halving_phase="unknown" en todos los trades ETH — no existe sizing size_ultra para ETH.
- 2024-2025: 5 trades perdedores seguidos. ETH underperformo BTC drasticamente en ese ciclo.
- T2+T4+T8 = 97% del profit de ETH. Mas concentrado aun que BTC.
- Los stops funcionan: maximo perdedor -16.41%.

### 3. Sensitivity analysis ✅ COMPLETADO (2026-06-29) — ADX re-corrido con bug fix, partial_exit confirmado

Resultados (realistic, 2018-2026):

| Variante | CAGR | dCAGR | Max DD | PF | dPF | Trades | Diagnostico |
|----------|------|-------|--------|----|-----|--------|-------------|
| DEFAULT v12 (adx=15) | +24.7% | — | 42.6% | 3.64 | — | 12 | referencia |
| score_min=8 | +24.3% | -0.4pp | 41.7% | 3.38 | -0.26 | 12 | ROBUSTO |
| score_min=10 | +25.8% | +1.1pp | 42.9% | 4.26 | +0.62 | 12 | ruido estadistico (ver nota) |
| adx_min=10 | +25.7% | +1.0pp | 39.1% | 3.78 | +0.14 | 12 | ROBUSTO — mismos trades |
| adx_min=20 | +27.4% | +2.7pp | 42.6% | 5.61 | +1.97 | 11 | POSIBLE OVERFITTING (ver nota) |
| trail_bull=0.24 | +19.7% | -5.0pp | 51.6% | 2.71 | -0.93 | — | MUY FRAGIL |
| trail_bull=0.32 | +27.5% | +2.8pp | 42.6% | 3.78 | +0.14 | — | mejora marginal |
| cooldown_atr=15d | +21.9% | -2.8pp | 52.0% | 3.26 | -0.38 | — | FRAGIL |
| cooldown_atr=45d | +24.7% | +0.0pp | 42.6% | 3.64 | +0.00 | — | ROBUSTO |

Journals ADX (2026-06-29):
- adx=10: `backtests/journal_pro_trend_btc_usdt_BTCUSDT_1H_20260629_080548.json`
- adx=20: `backtests/journal_pro_trend_btc_usdt_BTCUSDT_1H_20260629_080539.json`

**BUG (ya corregido):** `adx_min_entry` no estaba en `from_dict()`/`to_dict()`. Fix aplicado
en pro_trend.py. Las variantes ADX de la sesion 2026-06-28 eran invalidas (corrieron con 15.0).

Conclusiones sensitivity completas:

1. **trailing_stop_pct_bull es el parametro mas sensible** — asimetrico: 0.24 destroza
   el resultado (-5pp CAGR, DD sube 9pp a 51.6%), 0.32 mejora (+2.8pp, DD identico). El trailing
   esta "al borde". Senial de alarma en live: si BTC corrige 25-28% en una posicion, el stop
   esta muy cerca del limite.

2. **cooldown_atr_stop_days=30 es el minimo robusto** — 15d empeora (-2.8pp, DD +9.4pp),
   45d identico a 30d. Confirmado: 30d correcto.

3. **entry_score_min=9 es robusto hacia abajo** — score_min=8 da -0.4pp/-0.26 PF (robusto).
   score_min=10 da PF 4.26 vs 3.64 pero con 12 trades es ruido estadistico. Score=9 loser
   identificado: Q3-2019 (2019-08-09, BTC $11,972), h4_swing=downtrend, MFE=0 — pillado en
   cima de la recuperacion 2019. No es fallo sistematico. No cambiar score_min.

4. **ADX gate confirmado — adx=15 es correcto:**
   - adx=10: mismos 12 trades que default. Ningun trade historico entro con ADX 10-14.9.
     El gate en 15 no era arbitrario — ya estaba en el limite real de los datos. DD incluso
     mejora marginalmente (39.1% vs 42.6%), probablemente por timing de entrada ligeramente
     distinto.
   - adx=20: filtra 1 trade (perdedor Q2 2021), PF salta a 5.61. SOSPECHOSO — es fitting
     sobre 1 trade de una muestra de 12. En live podria bloquear ganadores. No cambiar.
   - Conclusion: adx_min=15 confirmado como robusto y correcto.

### 4. Journal MAE/MFE/R-multiplo ✅ COMPLETADO (2026-06-29)
Implementado en `reporting/trade_journal.py` y `strategies/base_strategy.py`.
BTC 2015-2026: avg MAE 8.1%, avg MFE 76.2%, max MAE 19.3%, avg R 2.51.
Losers ~-1R, ganadores 4-16R — asimetria confirmada en datos reales.

### 5. Partial exit ablation ✅ COMPLETADO (2026-06-30) — DEFAULT 150%, REVALIDAR 200%

| Config | P&L% | CAGR | PF journal true | Avg R | Nota |
|--------|-------|------|----|-------|------|
| DEFAULT (sin partial exit) | +480.5% | +24.7% | 3.64 | — | referencia v12 |
| partial_exit=150% | +521.84% | +25.7% | 4.64 | 2.06 | default v13 |
| partial_exit=200% | +541.59% en journal balance | pendiente | 3.69 | 1.96 | necesita rerun limpio |

Journals: `20260629_153048` (150%), `20260629_153049` (200%).
**partial_exit_pct=150.0 incorporado al default en pro_trend.py (v13), pero revalidar contra 200%**
tras corregir/interpretar el journal de partial exits. En runs con partial exit, usar balance final
o `balance_after - balance_before`, no solo `close.pnl_usdt`.

### 6. BTC 2015-2026 ✅ COMPLETADO (2026-06-30) — 3 ciclos bull validados

Journal: `backtests/journal_pro_trend_btc_usdt_BTCUSDT_1H_20260629_155853.json` (sin partial_exit)
Resultado: +5811%, CAGR +44.9%, PF 4.96, 20 trades (11W/9L), Sharpe 1.12
MAE avg 8.1%, MFE avg 76.2%, avg R 2.51 — asimetria solida en 20 trades.
Q4 2017: +$68,770 (trade mas grande de la historia). Estrategia funciona en 3 ciclos.
Nota: 2017 no se captura si start=2017 (warmup 380d lo consume). Necesita start 2015.

Pendiente confirmar: BTC 2015-2026 CON partial_exit=150% (v13 default). Comando:
```
python main.py backtest --strategy pro --from 2015-01-01 --to 2026-01-01 --costs realistic
```
(ya no hace falta --config porque 150% es el default en v13)

### 7. Paper trading Pro Trend — SIGUIENTE PASO OBLIGATORIO
Paper trading MANDATORIO min 6 meses con sizing 50% antes de capital real:
```bash
python main.py start --strategy pro --symbol BTC-USDT --config '{"size_ultra": 0.45, "size_high": 0.40, "size_mid": 0.30}'
```
Config paper: sizing al 50% del normal. partial_exit_pct=150.0 ya en default (v13).
Monitorear: frecuencia de entries (<3/mes), losses >20%, cooldown activo.

### 8. Swing Allocator v1 — ADOPTADO COMO DEFAULT ✅ (2026-06-30)

**Validaciones completadas:**
- Walk-forward v0: 4/4 ✅ (CAGR: +15.8%, +31.3%, +5.8%, +79.8%)
- ETH v0 2020-2026: +56.4% CAGR, PF 2.80, 37 trades ✅ — mecanismo causal confirmado
- Sensitivity 15 variantes: candidata v1 identificada ✅
- **Walk-forward v1: 4/4 ✅ (CAGR: +15.9%, +34.4%, +10.8%, +82.1%) — GATE SUPERADO**
- **Codigo actualizado: `delta_post_halving=0.20, delta_bear_onset=-0.20` son los nuevos defaults**
- **Toggles actualizados: `use_mvrv/rsi/pi_cycle/vix/macd_4h = False` en SwingAllocatorConfig**
- **ETH v1 2020-2026: +56.4% CAGR, PF 2.80, 37 trades ✅ — identico a v0 (ETH sin halvings)**
- **BTC conservative 2015-2026: +69.8% CAGR, PF 16.16, Max DD -56.59% ✅ — supera B&H**
- **Buffer slippage: 0.998 → 0.9965 (0.35%) — fix "Saldo insuficiente" en conservative**

**Tabla sensitivity (realistic, 2018-2026, base=regime+halving):**

| Variante | CAGR | dCAGR | PF | Trades | Max DD | Diagnostico |
|----------|------|-------|----|--------|--------|-------------|
| REF (halving=±0.10, regime=±0.20, thresh=0.10) | +33.5% | — | 2.79 | 53 | -54.82% | referencia v0 |
| min_btc=0.20 | +33.7% | +0.2pp | 2.74 | 55 | -54.82% | ruido |
| min_btc=0.40 | +31.2% | -2.3pp | 2.16 | 52 | -57.39% | PEOR |
| threshold=0.05 | +33.4% | -0.1pp | 2.76 | 66 | -54.42% | mas costes, sin ganancia |
| threshold=0.15 | +34.3% | +0.8pp | 3.37 | 44 | -54.11% | CANDIDATO individual |
| threshold=0.20 | +30.2% | -3.3pp | 15.67 | 17 | -55.96% | muy pocos trades |
| delta_regime=±0.15 | +34.3% | +0.8pp | 3.94 | 48 | -51.82% | CANDIDATO individual |
| delta_regime=±0.25 | +33.5% | +0.0pp | 2.93 | 51 | -55.33% | neutro |
| **delta_halving=±0.20** | **+36.7%** | **+3.2pp** | **3.77** | **50** | **-58.11%** | **CANDIDATA v1** |
| MVRV only | +33.0% | -0.5pp | 2.29 | 63 | -52.80% | PEOR — mas trades, sin alpha |
| Pi Cycle only | +33.4% | -0.1pp | 2.65 | 53 | -54.82% | neutro — descartado |
| MVRV + Pi Cycle | +33.8% | +0.3pp | 2.40 | 62 | -52.71% | PEOR |
| regime=0.15 + thresh=0.15 | +31.8% | -1.7pp | 9.54 | 21 | -53.62% | RECHAZADO (pocos trades, peor CAGR) |
| **halving=0.20 en 2015-2026** | **+77.4%** | **+6.9pp** | **2.46** | **68** | **-60.79%** | **CANDIDATA v1 validada** |
| full combo (regime=0.15+thresh=0.15+halving=0.20) | +35.1% | +1.6pp | 10.12 | 21 | -53.62% | pendiente WF |

**Candidata v1: `delta_post_halving=0.20, delta_bear_onset=-0.20`**
- 2018-2026: +36.7% CAGR, PF 3.77, 50 trades, Max DD -58.11%
- 2015-2026: +77.4% CAGR, Sharpe 1.25, $5.48M (vs $3.53M de v0 y ~$2.78M B&H)
- Mecanismo: mas exposicion en post_halving/bull_peak (hasta 100% BTC) captura mas del bull run
- Coste: DD sube 5-8pp vs v0. Sigue siendo mejor que B&H (-77% max DD historico)

**Tests pendientes de segunda ronda (TODOS sobre datos fijos — cache ya garantiza determinismo):**
- ~~**PRIORIDAD: test de fragilidad del punto de inicio.**~~ ✅ COMPLETADO (2026-07-01, sesion 13).
  Medido v1 con inicio 2015/2016/2017 sobre datos cacheados. VEREDICTO: la fragilidad es de la
  METRICA (PF), no del edge. CAGR robusto (78.0-81.2%, varia 3pp) y Max DD robusto (-57.2% a -58.7%).
  PF fragil (2.51/3.70/4.33) porque lo dominan los pocos trades monstruo y arrancar en 2015 deja mas
  capital componiendo antes del bull 2017 (Q4 2017: +$157k con start 2015 vs +$51k con start 2017) y
  sube win rate a 55.4% vs ~51%. El "PF 4.33" es propiedad de EMPEZAR EN 2015, no de la estrategia.
  ACCION: comparar candidatos por CAGR y Max DD (anclas estables), reportar PF como rango, fijar
  siempre inicio 2015. Los 3 baten a B&H y todos PF>2.5 → tesis intacta. Q4 2025 negativo en los 3
  (peor 2016: -$265k, 0% win) → ping-pong estructural, independiente del arranque.
- ~~Baseline realistic fresco~~ ✅ COMPLETADO: +78.4% CAGR, 65 trades, PF 4.33, Max DD -57.60%
- ~~Analisis Q4 2025~~ ✅ COMPLETADO: causa identificada — ver seccion "Q4 2025 analisis" abajo
- ~~`min_days_between_rebalance=7`~~ ✅ DESCARTADO: empeora Q4 2025 (-10.4% vs -3.3%) y pierde $190k vs v1
- ~~`adx_min_regime=20` (ADX gate simetrico)~~ ✅ DESCARTADO (sesion 12): no arregla Q4 2025,
  reubica el ping-pong a la frontera del ADX, sube trades 65→103. Revertido del codigo.
- `delta_post_halving=0.15` — punto medio entre 0.10 y 0.20
- `halving=0.20 + threshold=0.15` sin bajar regime delta
- Deltas asimetricos: `delta_regime_bull=0.15, delta_regime_bear=-0.25` (salir mas rapido en bear)
- `base_btc_pct=0.50` y `base_btc_pct=0.70`
- `adx_min_trend=20` y `=25`
- `min_btc=0.20 + halving=0.20`

**Q4 2025 mitigacion — PENDIENTE (proxima sesion, sobre datos fijos):**
Causa: conflicto `halving_bear_onset` (-0.20) vs `regime_bull` (+0.20) con BTC lateral $103-112k.
EMA50D/200D cruzaba en ambas direcciones cada 3-5 dias → ping-pong 60%↔40% BTC con fees.
Cooldown=7d descartado: no resuelve el conflicto de senales, empeora la perdida (-$280k vs -$129k).
Opcion 2 (ADX gate) DESCARTADA sesion 12: reubica el ping-pong, no lo elimina. Queda una via viva:
1. **Cap target con halving_bear_onset activo (PROXIMO INTENTO):** cuando `bear_onset` esta activo,
   `regime_bull` no puede subir el target por encima de `base_btc_pct` (0.60). Determinista, no depende
   de un umbral que oscila (por eso el ADX fallo). Requiere cambio en `_compute_target()`, tras un flag
   reversible. Testear contra baseline v1 anclado (PF 4.33) sobre datos cacheados.
2. ~~ADX minimo para regime signal (`adx_min_regime`)~~ ✅ DESCARTADA sesion 12: probada a ADX=20,
   no arregla Q4 2025 (sigue 4-6 rebalanceos), sube trades 65→103. El ADX oscila en lateral igual
   que el EMA. Revertida del codigo.

**Q4 2025 analisis (2026-06-30) — causa identificada, mitigacion pendiente:**
El 12-oct-2025 son ~540 dias desde el halving de abril-2024: `halving_bear_onset` activa (-0.20).
Pero `regime_bull` (EMA50D > EMA200D) tambien esta activo (+0.20). BTC lateral $103-112k.
Resultado: EMA50D cruzaba EMA200D en ambas direcciones cada 3-5 dias → 8 rebalanceos en 3 semanas:
  compra a ~$109-111k, vende a ~$103-108k repetidamente. -$129k sobre portfolio de $6.8M (-1.9%).
Peor swap: compra $110,566 → vende $102,982 (-7%) en 3 dias.
Raiz: `min_days_between_rebalance=3` es exactamente la frecuencia del EMA crossover oscillation.
Cooldown=7d descartado — empeora a -$280k (-10.4%) porque el sistema no puede salir rapido cuando cambias senales.
Mitigacion pendiente: cap target en bear_onset o ADX minimo para regime. Ver "Q4 2025 mitigacion" arriba.

**Criterio go/no-go (SWING_PLAN.md) — TODOS SUPERADOS:**
- CAGR > B&H en 2pp en 2015-2026 ✅ (+10.6pp con v1) y 2018-2026 ✅ (+10.3pp con v1)
- Walk-forward 3/4 ventanas positivas: ✅ v1 (4/4)
- ETH no negativo ✅ (+56.4% CAGR con v1 — identico a v0, ETH sin halvings)
- Max DD <= B&H ✅ (-60.79% realistic, -56.59% conservative, vs -77% B&H)
- Costs conservative: ✅ +69.8% CAGR (supera B&H ~66.8%)

---

## RESULTADOS DE BACKTEST

| Estrategia | Periodo | Balance | P&L | Trades | PF | CAGR |
|------------|---------|---------|-----|--------|----|------|
| **Swing Allocator v1 DEFAULT (halving=±0.20, WF 4/4)** | 2015-2026 | $5,809,599 | +57996% | 65 | 4.33 | +78.4% |
| **Swing Allocator v1 DEFAULT (halving=±0.20, WF 4/4)** | 2018-2026 | $121,626 | +1116% | 50 | 3.77 | +36.7% |
| **Swing Allocator v0 (regimen+halving)** | 2015-2026 | $3,531,807 | +35218% | 64 | 3.38 | +70.5% |
| **Swing Allocator v0 (regimen+halving)** | 2018-2026 | $109,096 | +990.96% | 52 | 3.08 | +34.8% |
| **Pro Trend v13 (realistic, partial_exit=150%)** | 2018-2026 | $62,184 | +521.8% | 12 | 3.89 | +25.7% |
| **Pro Trend v13 (realistic)** | 2015-2026 | $591,169 | +5812% | 20 | 4.96 | +44.9% |
| Swing Allocator (sin senales, baseline) | 2015-2026 | $774,673 | +7646% | 14 | 7.50 | +48.5% |
| Swing Allocator (full signals) | 2015-2026 | $1,279,984 | +12699% | 249 | 1.44 | +55.4% |
| BTC Buy & Hold (realistic) | 2018-2026 | ~$64,971 | +549.7% | — | — | +26.4% |
| BTC Buy & Hold (realistic) | 2015-2026 | ~$2,779,400 | +27694% | — | — | ~+66.8% |
| Pro Trend v12 (ideal) | 2018-2026 | $71,412 | +614% | 11 | 5.81 | +28.0% |
| Pro Trend v12 (realistic) | 2018-2026 | $58,050 | +480.5% | 12 | 3.64 | +24.7% |
| Adaptive Trend (realistic) | 2018-2026 | ~$48,090 | +380.9% | 20 | 2.91 | +21.8% |
| Scalp Momentum v4 | 2022-2026 | $9,640 | -3.6% | 351 | 0.93 | -0.8% |

### Distribucion profit v12 (costes ideal)
- T4 Q1-2021: +$16,442 | T5 Q2-2021: +$17,111 | T9 Q3-2024: +$21,323
- T10 Q1-2025: +$9,989 (out-of-sample) | T11 Q4-2025: +$7,850 (out-of-sample)
- 5 perdedores: ~-$12,767
- **ADVERTENCIA: T4+T5+T9 = 89% del profit**

### Baselines comparativos (realistic, 2018-2026) — CORREGIDOS 2026-06-26
| Estrategia | P&L | CAGR | Max DD | Sharpe | PF | Trades | T.mkt |
|---|---|---|---|---|---|---|---|
| Pro Trend v12 completo | +480.5% | +24.7% | 42.6% | 0.74 | 3.64 | 12 | 35% |
| Pro Trend sin filtros externos | +492.6% | +25.0% | 42.3% | 0.75 | 3.69 | 12 | 36% |
| Pro Trend score_min=1 (gates only) | +443.3% | +23.7% | 38.5% | 0.72 | 3.74 | 12 | 37% |
| Pro Trend sizing fijo 50% | +229.7% | +16.2% | 29.3% | 0.63 | 4.08 | 12 | 35% |
| Adaptive Trend (mas simple) | +380.9% | +21.8% | 36.5% | 0.68 | 2.91 | 20 | 41% |
| **Buy & Hold BTC** | **+549.7%** | **+26.4%** | — | — | — | — | 100% |

Conclusiones (ver analisis completo en historial sesion):
- Filtros externos: decorativos en historico. Mismos 12 trades. +$1,207 sin externos. Mantenerlos.
- Scoring: NO filtra trades en BTC. Impacto solo en exit timing (+$3,743 con score_min=9).
- Sizing adaptativo: UNICO driver real. Dobla el resultado vs fijo 50%.

### ETH Backtest (realistic, 2020-2026) — COMPLETADO 2026-06-26
| Metrica | ETH | BTC (ref) |
|---|---|---|
| P&L | +370.7% | +480.5% |
| CAGR | +29.4% | +24.7% |
| B&H | +2230% | +549.7% |
| Win rate | 30.8% (4/13) | 50% (6/12) |
| PF | 1.77 | 3.64 |
| Max DD | -42.76% | -42.6% |
| T.mkt | 30.1% | 35% |
Anti-overfitting: confirmado (PF>1.0 en activo diferente). Edge mas debil por ETH/BTC ratio divergente 2024-25.

### Walk-Forward (realistic, 4 ventanas — 1 invalida)
| Ventana TEST | CAGR | PF | Trades | vs B&H |
|---|---|---|---|---|
| 2022-2023 | +10.7% | — (1W) | 1 | Gana (B&H ~-10%) |
| 2024-2026 | +12.2% | 4.22 | 4 | Pierde (B&H ~+150%) |
| 2021-2022 | +6.3% | 1.24 | 4 | Gana (B&H ~-43%) |
| 2023-2025 | +43.3% | 8.56 | 2 | Solo 2 trades |
| TRAIN 18-21 | — | — | 0 | INVALIDA (fallo descarga OKX) |

---

## PRO TREND v12 — REFERENCIA COMPLETA

### 13 gates de entrada long (en orden)
VIX < 35 → score >= 9 → ventaja > 2 → weekly_trend not False → h4_bullish not False
→ MVRV < 3.0 (long_reduce_risk=False) → funding < 0.0005 → DXY no headwind
→ NASDAQ no risk-off → Pi Cycle Top inactivo → RSI ok (0=off) → ATR ok (0=off)
→ ADX >= 15.0 → MACD alcista en D o 4H
Gates como variables `_g_*` en run() para diagnostico en logs.

### ProTrendConfig — valores actuales v13
```python
entry_score_min         = 9      # todos los ganadores historicos tuvieron score >= 9
adx_min_entry           = 15.0   # bloquea mercados sin tendencia
entry_score_gap         = 2
exit_score_floor        = 3
size_ultra              = 0.90   # post_halving/bull_peak con score >= 8
size_high               = 0.80   # fuera de bull phase con score >= 8
size_mid                = 0.60   # score < 8
size_short_cap          = 0.15
trailing_stop_pct       = 0.22   # bear/accumulation
trailing_stop_pct_bull  = 0.28   # post_halving/bull_peak
cooldown_bear_days      = 30
cooldown_trailing_bull_days = 7
cooldown_atr_stop_days  = 30
max_loss_pct            = 20.0
atr_stop_mult           = 3.0
partial_exit_pct        = 150.0  # vende 33% al +150% — confirmado 2026-06-30 (+1pp CAGR)
partial_exit_size       = 0.33
allow_shorts            = False
macd_exit_enabled       = False
lookback_hours          = 15000  # 625 dias para SMA350D (Pi Cycle Top)
pi_cycle_enabled        = True   # auto False para no-BTC en main.py
disable_external_filters = False # True solo para ablation tests
```

### Sizing adaptativo
- `size_ultra` (90%): score >= 8 en post_halving/bull_peak
- `size_high` (80%): score >= 8 fuera de bull phase
- `size_mid` (60%): score < 8
- Ajustes: bear_onset x0.75 | MVRV euphoria cap 20% | VIX>22 cap size_mid (fix aplicado 2026-06-30, pendiente backtest) | VIX>35 bloqueo | shorts cap 15%

### Cache de indicadores
- `_daily_cache`: {"date": "YYYY-MM-DD", "ind": {...}}
- `_weekly_cache`: {"week": "YYYY-Www", "ind": {...}}
- `_4h_cache`: {"key": "YYYY-MM-DD-N", "ind": {...}} donde N = hora // 4

### Cooldown (date-based, no barras)
- ATR stop: 30 dias (`cooldown_atr_stop_days`)
- Hard stop: 15 dias
- Trailing stop bear/accum: 30 dias (`cooldown_bear_days`)
- Trailing stop bull: 7 dias (`cooldown_trailing_bull_days`)

### Sistema de puntuacion long (max ~14 pts)
+2 tendencia semanal alcista | +1 EMA50D>EMA200D | +1 precio>EMA200D | +1 slope EMA50D+
+1 swing uptrend | +2 MACD crossover (+1 si solo positivo) | +2 RSI div alcista
+1 OBV slope+ | +1 ADX>20 con golden cross | +1 soporte S/R o VAL
+1 FVG alcista | +1 vol spike alcista | +1 BB dip/squeeze breakout

### Shorts sinteticos (allow_shorts=True)
No ordenes reales OKX. Margen USDT reservado via `adjust_balance()`. Registrados via `_log_short_trade()`.
CRITICO: `OrderResult` requiere `size=qty, limit_price=None`.

---

## MACRO CONTEXT (macro_context.py)

Fuente: CoinMetrics Community API (gratuito, sin API key).
Metricas: `CapMVRVCur` + `PriceUSD`. `PriceRealizedUSD` NO disponible en tier gratuito.
Realized Price = PriceUSD / CapMVRVCur.
URL: usar `%2C` para separar metricas (comma URL-encoded).

MVRV umbrales actuales: deep_bear<1.0 | recovery<2.0 | bull 2.0-3.0 | late_bull 3.0-3.5 | euphoria>3.5
- `long_reduce_risk=True` si MVRV >= 3.0
- Maximo historico backtests: ~2.96 (Q2 2021) — por eso MVRV es filtro casi decorativo en 2018-2026

Halvings BTC: 28-Nov-2012, 9-Jul-2016, 11-May-2020, 20-Abr-2024, ~15-Mar-2028 (estimado)
Fases: post_halving(0-180d) | bull_peak(180-540d) | bear_onset(540-900d) | accumulation(>900d)

Modo degradado: `short_allowed=True, long_reduce_risk=False` si falla CoinMetrics.

---

## MARKET CONTEXT (market_context.py)

Fuente: Yahoo Finance API (urllib, User-Agent obligatorio o da 403).
Tickers: `^DXY`, `^NDX`, `^VIX`

Senales:
- `dxy_headwind`: DXY subio > 1.5% en 10 dias → bloquea longs
- `risk_off`: NASDAQ bajo > 5% en 10 dias → bloquea longs
- `vix_elevated`: VIX > 22 → cap sizing al 60%
- `vix_extreme`: VIX > 35 → bloqueo total de entrada

Modo degradado silencioso si falla Yahoo Finance.

---

## FUNDING CONTEXT (funding_context.py)

OKX liquida 3 veces/dia (00:00, 08:00, 16:00 UTC).
`get_funding_rate_at(dt)`: siempre delta >= 1 (dia anterior completo) — lookahead fix.
Umbral: > 0.0005 bloquea longs; < -0.0005 bloquea shorts.

---

## INDICADORES (strategies/indicators.py — UNICO modulo activo)

`ema`, `sma`, `macd`, `atr`, `rsi`, `adx`, `obv`, `ema_slope`, `bb_bands`,
`swing_structure`, `sr_levels`, `fvg_zones`, `rsi_divergence`,
`resample_to_1h`, `resample_to_4h`, `resample_to_daily`, `resample_to_weekly`,
`volume_profile` → (poc, vah, val)

RENDIMIENTO: resample_to_daily/weekly son O(n²) — mitigado con _daily_cache/_weekly_cache.

---

## ADAPTIVE TREND (adaptive_trend.py)

Estado: FUNCIONAL. Resultado 2018-2026 realistic: +380.9%, 20 trades, PF 2.91, CAGR +21.8%.
Solo longs. Logica: regimen (EMA50D/200D/ADX) → entrada MACD+RSI+vol → salida bear/MACD/RSI/ATR.

---

## SCALP MOMENTUM (scalp_momentum.py)

Estado: EN EVALUACION. Correr en 1H (no 15m).
Resultado v4 (15m): -3.6%, PF 0.75, 351 trades — no rentable.
```bash
python main.py backtest --strategy scalp --from 2022-01-01 --to 2026-06-01 --timeframe 1H
```

---

## OVERFITTING — THRESHOLDS EN RIESGO

Ajustados sobre solo 11 trades historicos — no se puede saber si son robustos:
- `entry_score_min=9` — 5 perdedores tuvieron score<9 en v10
- `adx_min_entry=15.0` — muy especifico para tan pocos trades
- `trailing_stop_pct_bull=0.28` — calibrado sobre crash Evergrande T5 2021
- `cooldown_atr_stop_days=30` — calibrado sobre brecha T8/T9 2024
- `atr_stop_mult=3.0` — subido porque 2.5 disparo T5 prematuramente

Walk-forward: 3/3 ventanas validas positivas → logica no es memorizacion pura.
Pero: 1-4 trades por ventana, base estadistica muy pequena.

Protocolo antes de capital real:
1. Baselines correcto → 2. ETH backtest → 3. Sensitivity analysis → 4. Paper trading 6 meses

Senales de alarma en live:
- Mas de 3 entries en un mes (historico: 1-2 por año)
- Trade pierde > 25% (hard stop es 20%)
- Score en entrada < 9
- Cooldown ignorado (revisar `_cooldown_until` en DB)

---

## EVOLUCION PRO TREND

| Version | Cambio clave | Impacto |
|---------|-------------|---------|
| v8 | macd_exit=False | +$8k vs v7 |
| v9 | trailing_bull=0.28, cooldown_atr=30d, sizing_bull=75% | +$6.7k |
| v10 | MVRV_FAIR=3.0, atr_mult=3.0, score_min=7 | |
| v10+VIX+Funding | VIX layers, funding historico | +$17.7k |
| v11 | score_min=9, sizes 90/80/60%, sin penalizacion acumulacion | +$19.3k |
| v12 | adx_min=15, gate MACD cross-TF, bear_onset×0.75 | ideal +614%, realistic +480% |
| v13 | partial_exit_pct=150% como default | +521% (2018-26), +5812% (2015-26), 3 ciclos bull |

---

## BUGS RESUELTOS (no re-investigar)

1. `_log_short_trade()` sin `size`/`limit_price` → añadidos al OrderResult
2. Weekly flip oscillation (miles de trades): fix `weekly_trend is not False` en long_ok
3. Sin cooldown tras weekly flip: fix `_set_cooldown()` date-based
4. `h1["close"]` no existia en dict fallback: fix añadir `"close": last_close`
5. UnicodeEncodeError Windows cp1252: sustituidos caracteres Unicode por ASCII
6. `adx_min_entry` no estaba en `from_dict()` / `to_dict()` de ProTrendConfig → el parametro
   existia en el dataclass y se usaba en el gate, pero `--config '{"adx_min_entry": X}'` lo
   ignoraba silenciosamente. Invalidó las variantes ADX del sensitivity analysis (todas corrieron
   con adx_min_entry=15.0). Fix: añadido a ambos metodos de serializacion.

---

## LO QUE NO HA FUNCIONADO

- Backtests anuales independientes — posiciones desaparecen, contexto se pierde
- Price reference con `daily["close"]` en lugar de `h1["close"]` — artificial
- RSI bearish div +2 pts en short score — demasiado ruido en bull markets
- Shorts activados en Pro Trend 2018-2026 — pierde en correcciones de bull market
- MACD cross exit en ScalpMomentum — cortaba ganadores antes del TP
- Swing Allocator baseline 60/40 sin senales — pierde 18pp CAGR vs B&H en 2015-2026. Rebalanceo mecanico vende BTC en subidas, reduce holdings para el siguiente tramo alcista. Solo funciona si las senales de regimen aumentan exposicion en bull markets.
- Swing Allocator full signals (RSI+VIX+MACD 4H+MVRV) — 249 trades, peor que regimen solo. Cada senal adicional sobre el regimen anado ruido y costes sin alpha neto. Senales de alta frecuencia (4H MACD, RSI diario) incompatibles con cooldown de 3 dias.
- MVRV en Swing Allocator — confirmado inutil en sensitivity. Anade trades sin alpha, PF cae de 2.79 a 2.29.
- Pi Cycle en Swing Allocator — neutro. Mismos trades, PF algo peor. No justifica la complejidad.
- regime=±0.15 + threshold=0.15 combinados — sistema demasiado restrictivo (21 trades en 8 anos). Individualmente cada uno mejora la referencia, juntos se anulan y empeoran CAGR (-1.7pp).
- threshold=0.20 — solo 17 trades en 8 anos, PF 15.67 es ruido estadistico puro. CAGR -3.3pp.

---

## DATOS EXTERNOS

| Fuente | Datos | Autenticacion |
|--------|-------|---------------|
| CoinMetrics Community API | MVRV (CapMVRVCur + PriceUSD) | Sin API key |
| Yahoo Finance | DXY, NDX, VIX | Sin API key, User-Agent obligatorio |
| OKX REST API | OHLCV historico, funding rate | Sin auth para publicos |
| Binance REST API | OHLCV fallback si OKX da 0 barras | Sin auth |

Multi-activo: MVRV disponible para BTC y ETH. SOL/BNB: degradacion silenciosa.
Pi Cycle Top solo BTC. Halvings solo BTC.

---

## JOURNAL (reporting/trade_journal.py)

`write_journal(journal, strategy_name, symbol, timeframe, from_date, to_date, cost_mode, config_overrides, resolved_config, backtest_summary)`
Archivo: `backtests/journal_{estrategia}_{simbolo}_{timeframe}_{ts}.json`
Meta incluye `cost_mode`, `config_overrides`, `resolved_config` y `backtest` para identificar
la sesion, config final exacta y resumen del resultado.

P0 implementado 2026-06-30: en estrategias con partial exits, el journal agrega `true_pnl_usdt`,
`true_pnl_pct`, `total_close_pnl_usdt`, `balance_pnl_adjustment_usdt` y `uses_balance_pnl`.
`pnl_usdt` se conserva como PnL del cierre final para auditoria.

P0 ampliado 2026-06-30 para Pro Trend:
- `meta.resolved_config`: config efectiva de la estrategia, incluyendo defaults no pasados por CLI.
- `meta.backtest`: balance inicial/final, retorno, B&H, CAGR, MaxDD, Sharpe/Sortino, trades, PF,
  win rate, expectancy, barras, warmup y costes.
- `open.size_pct`: porcentaje real de balance usado en la apertura.
- `open.indicators.sizing`: tier, size planificado, size real, diferencia real-plan, cap MVRV/VIX
  y balance/invest usado.
- `open.indicators.entry_gates`: estado de cada gate de entrada (`g_score`, `g_mvrv`, `g_funding`,
  `g_dxy`, `g_ndx`, `g_adx_min`, `g_macd_momentum`, etc.).
- `open/close.indicators`: MVRV regime, halving, realized price, VIX, DXY/NDX, funding,
  `partial_exit_triggered`, `half_reduced` y config de partial exit.
- `close.giveback_pct` y `close.exit_from_peak_pct`: cuanto se devolvio desde MFE hasta salida.
- `close.partial_exit_triggered`: si el trade tuvo partial exit antes del cierre final.

Nota Windows:
- PowerShell acepta `--config '{"partial_exit_pct": 150.0}'`.
- CMD requiere comillas escapadas: `--config "{\"partial_exit_pct\": 150.0}"`.

---

## SWING ALLOCATOR — REFERENCIA

### Archivos
- `strategies/swing_allocator.py` — estrategia completa (SwingAllocatorConfig + SwingAllocatorBot)
- `reporting/swing_journal.py` — journal de rebalanceos (distinto de trade_journal.py)
- `SWING_PLAN.md` — diseño completo, criterios go/no-go, plan de validacion

### Concepto
Mantiene siempre BTC en cartera (nunca sale del todo). Ajusta el porcentaje entre 30-100%
segun senales macro. Objetivo: batir B&H acumulando mas BTC en correcciones.

### SwingAllocatorConfig — versiones

**v1 (DEFAULT en codigo desde 2026-06-30):**
```python
base_btc_pct  = 0.60   # allocation neutral
min_btc_pct   = 0.30   # hard floor
max_btc_pct   = 1.00   # hard ceiling
rebalance_threshold        = 0.10
min_days_between_rebalance = 3
use_regime=True, use_halving=True
use_mvrv=False, use_rsi=False, use_pi_cycle=False, use_vix=False, use_macd_4h=False
delta_regime_bull=+0.20, delta_regime_bear=-0.20
delta_post_halving=+0.20, delta_bear_onset=-0.20   # v1: subido de ±0.10
```
Resultado: 2015-2026 +77.4% CAGR, 2018-2026 +36.7% CAGR, WF v1 4/4 ✅, Max DD -60.79%
Sin --config adicional: ya corre con v1 por defecto.

**v0 (referencia historica):**
```python
delta_post_halving=+0.10, delta_bear_onset=-0.10   # use_* todos True en v0
```
Resultado: 2015-2026 +70.5% CAGR, 2018-2026 +34.8% CAGR, WF 4/4 ✅

### Mecanismo por fases
- **Bull (golden cross + precio > EMA200D + ADX > 15):** target 80-90% BTC
- **Bear (death cross):** target 30-40% BTC
- **Resultado:** captura 80-90% de los bull runs, evita 60-70% de los bear markets
- Rebalanceo cada vez que la diferencia entre actual y target supera el 10%, con cooldown 3 dias

### Por que gana a B&H
El capital preservado en bear phases (USDT) compra mas BTC en la recuperacion.
Ejemplo 2022: B&H pierde ~77% desde peak. Swing en 30% BTC pierde ~23%.
Ese USDT compra BTC barato en 2023, que luego sube x5 en 2024-2025.

### Fixes implementados (2026-06-30)
1. **Slippage buffer**: `buy_usdt = min(delta_value, usdt_bal * Decimal("0.998"))` — evita "saldo insuficiente"
2. **Signals logging**: `_compute_target()` devuelve `(target, active_signals)` — cada rebalanceo registra que senales lo dispararon
3. **BTC acumulado**: journal incluye `final_btc_qty`, `bnh_initial_btc`, `btc_vs_bnh_ratio` — metrica clave para holders
4. **Signal frequency**: journal incluye mapa de frecuencia por tipo de senal

### Bugs resueltos (no re-investigar)
- "Saldo insuficiente" en full signals: fix inicial con buffer 0.2%
- "Saldo insuficiente" en conservative (15bps slippage): buffer aumentado a 0.35% (`Decimal("0.9965")`) — coste total conservative es 0.25%, buffer previo era insuficiente
- Signals vacias en journal: fix aplicado devolviendo active list desde `_compute_target`

### Comando de referencia
```bash
python main.py backtest --strategy swing --from 2015-01-01 --to 2026-01-01 --costs realistic \
  --config "{\"use_mvrv\":false,\"use_rsi\":false,\"use_pi_cycle\":false,\"use_vix\":false,\"use_macd_4h\":false}"
```


---

## SNAPSHOT SESSION.md sesiones 14-18 (migrado 2026-07-06)

> Volcado integro del SESSION.md HOT previo al recorte de arranque (2026-07-06).
> Contiene los bloques HECHO/Descartado de sesiones 14-18 y el detalle de prop/Hyro que
> antes se cargaba cada turno. Las REGLAS INVARIANTES siguen viviendo en SESSION.md (no aqui).

# SESSION.md — Estado del proyecto (HOT — se carga en cada sesion via @SESSION.md)

Complemento de CLAUDE.md. **Este archivo es deliberadamente corto** para no gastar tokens en
cada arranque. El detalle historico completo (logs de sesion, tablas de backtests, referencia de
cada modulo) vive en **`SESSION_ARCHIVE.md`** — leelo SOLO cuando lo necesites, no por defecto.

**Ultima actualizacion: 2026-07-06 (Swing v6 + aislamiento paper + pipeline funding MERGEADO A MAIN)**

**HECHO (2026-07-06): merge a main + pipeline de funding vivo para el overlay v6.**
- La rama `codex-handoff-prop-cft-swing-v6` esta MERGEADA A MAIN (fast-forward @ `2019859`,
  pusheado a origin). main default sigue siendo v5 intacto: smoke CLI reproduce el ancla exacta
  ($9.164M / +85.9% / -52.73% / btc_vs_bnh 0.8171 / 96930 velas). Todo lo v6/prop entra detras de
  flags default `False`. Tests 145/145.
- **Aislamiento de carteras paper**: `OKXClient(paper_state_name=...)` -> cada bot con
  `paper_portfolio_id` en su config usa su propio `data/runtime/paper_state_<id>.json`. Los bots
  legacy SIN `paper_portfolio_id` (el v5 que ya corre en la VM) siguen en `paper_state.json` sin
  cambios. v6 -> `swing_v6`; Prop/CFT -> `prop_cft`. `tools/swing_paper_setup.py` registra v6
  (y v5 aislado con `--include-v5`); `tools/prop_cft_setup.py` registra el prop.
- **Pipeline de funding vivo** (`tools/funding_refresh.py`): descarga settlements nuevos de Bybit
  y los fusiona en `data/cache/funding_bybit_BTCUSDT.json` (dedup por ts, escritura atomica);
  `--stale-hours` sale !=0 para alertar. Enganchado en el cron diario (`deploy/daily_checks.sh`)
  antes de la paridad, con alerta Telegram si el cache se queda atras (umbral 26h).
- **Fix degradacion silenciosa**: `swing_funding_overlay._cached_events` se keyea por mtime del
  archivo -> un scheduler que corre semanas recomputa cuando el cron refresca (antes congelaba los
  eventos del primer tick). Log "overlay skipped" sube de debug a warning.
- **El cache de funding pasa a gitignore** (`data/cache/funding_bybit_*.json`): lo modifica un cron
  a diario y chocaria con `/update`. Funding history Bybit es inmutable/re-descargable, el
  determinismo sobrevive a re-fetch. OJO en la VM: el pull BORRA el archivo -> reconstruir con
  `python tools/funding_refresh.py` tras el pull (no urgente: overlay dormido hasta accumulation).
- **v6 NO es ADOPT**: sigue `NEEDS_MORE_VALIDATION` (SWING_V6_PLAN.md). El overlay SOLO dispara en
  fase `accumulation`; hoy estamos en `bear_onset` (807 dias post-halving), asi que v6 ≡ v5 en vivo
  hasta ~2026-10-07 (dia 900). El paper v5-vs-v6 solo dara divergencia a partir de entonces.
- **Deploy VM (los 3 en paper)**: `git pull` -> `pip install -r requirements.txt` (nueva dep
  `matplotlib`, lazy, no bloquea) -> `python tools/funding_refresh.py` -> `swing_paper_setup.py
  --enable` (SIN `--include-v5`, para NO crear un v5 fresco y perder el legacy) -> setup prop ->
  `systemctl restart matibot` -> `bot list` (deben salir los 3). v5 legacy (`paper_state.json` +
  `trading.db`, gitignored) intacto.

Punteros a referencia (leer bajo demanda, NO precargar):
- `HANDOFF_2026-07-05.md` — documento principal para continuar en otro PC sin perder contexto
  (branch, setup, estado operativo, Prop/CFT, Swing v6, tests y siguientes pasos).
- `SWING_V6_PLAN.md` — plan v6: phase policy router (v5_equiv exacto) + funding overlay (V6-2
  p10/p90 +0.05 ttl 7d en accumulation = candidato vivo, NEEDS_MORE_VALIDATION). Criterios de
  promocion (Fase 4): requiere evidencia forward/paper post-2026-01-01 para pasar a ADOPT.
- `SESSION_ARCHIVE.md` — logs sesiones 12/13, auditoria 2026-06-30, resultados backtest, referencia
  detallada de Pro Trend v12/v13, macro/market/funding context, indicadores, bugs resueltos.
- `backtests/STRATEGY_VERSIONS.md` — historial de versiones de estrategia.
- `SWING_PLAN.md` — diseno y criterios go/no-go del Swing Allocator.
- `AUDITORIA_SWING_V4.md` — auditoria cuantitativa critica (2026-07-02): hallazgos B1-B5/C1-C9,
  sensibilidad calendario halving, ablations, tabla por anios. `PLAN_MEJORA_AUDITORIA.md` — plan
  paso a paso (F1-F19) para resolverlos (COMPLETADO salvo cierres que requieren paper: F13/F15/F19).
  `AUDITORIA_SWING_V5_POST_IMPLEMENTACION.md` — auditoria post-implementacion del freeze v5.
  Scripts en `tools/` (sens_phases, bootstrap_equity, stress_usdt_depeg, swing_benchmarks,
  swing_parity_check, degradation_report, swing_v5_freeze_report).
- Journals: NO hacer `Read` del JSON crudo (pueden ser >10 MB). Usar
  `python tools/journal_summary.py <ruta>` o `/journal-summary`.
- `HYROTRADER_PLAN.md` — estrategia prop firm (HyroTrader/Bybit). Estado final 2026-07-03:
  P0-P4 COMPLETADOS y **checkpoint FASE 7 disparado — NO comprar challenge**. Mejor candidato
  (prop_swing breakout + risk 1%): P(pasar) 11.8% << 60% go/no-go; EV negativo. Queda listo:
  `core/prop_rules.py` (simulador reglas prop), `strategies/prop_swing.py` (entry_mode
  pullback|breakout), `tools/prop_challenge_sim.py`. Swing v5 por el simulador = breach 100%
  (baseline). Retomable solo con un motor nuevo que de P(pasar)>=60% en el simulador.
  Sesion 17 (2026-07-03, secciones 10-12 del plan): H1 palancas gratis insuficientes y
  bull-start REFUTADO; H2 shorts sinteticos con MTM (`allow_shorts`) = E8, ~2-4x pass;
  H3 ETH RECHAZADO (sin edge, no reintentar); H4 squeeze RECHAZADO (mata el edge).
  Hallazgo clave: `max_notional_pct=0.25` clampeaba el riesgo efectivo de TODO el
  proyecto (~0.25-0.75% real). E9 = E8 + cap 0.5 (legal en perps con leverage) llego a
  two-step 64%/one-step 73% realistic PERO **VEREDICTO FINAL: NO-GO** — con costes
  conservative cae a 37-44% two-step y breach 27-42% (criterios: >=60% y <=20%), y el
  funding de perps ni esta modelado. Seccion 12: balance, hallazgos, condiciones de
  reapertura. Config E9 congelada en el plan; flags reversibles en prop_swing.
  **Matias decide NO cerrar** -> **PLAN B (seccion 13)**: N0 testnet Bybit para medir
  costes REALES con E9 (el no-go fue por supuestos de slippage, no medidas) + N1 modelo
  Bybit en backtest + N2 screens de alfa no-indicador con datos existentes
  (estacionalidad, funding extremo, settlement drift, post-barrida) + N4 motores + N5
  meta-labeling (ultimo recurso). Presupuesto duro: sin efecto en N2 y costes reales
  >=12bps -> cierre sin apelacion. Seccion 14: E9 standalone vs Swing v5 — rentable
  (CAGR +9.2% 2015-26, DD -21%, 10/11 anios verdes) pero dominado por el Swing tambien
  en riesgo-ajustado (Calmar 0.43 vs 1.63); rol de E9 = solo prop. ALERTA: 2025 unico
  anio negativo (-$3.9k) y el Max DD es Q1-24->2025 (degradacion reciente del motor).
  N2 EJECUTADO (`tools/alpha_screens.py` + funding Bybit cacheado): hora-del-dia y
  post-barrida MUERTOS tras dedup (leccion: deduplicar senales solapadas SIEMPRE);
  dia-de-semana marginal; **funding extremo = unico superviviente** (p95: +92bps
  mediana f72, WR 65%, 6/6 anios; p05: +58bps, 5/6; ambas colas long, ~30 senales/anio).
  N1+N4 EJECUTADOS (sesion 18, 2026-07-04, seccion 15 del plan): modelo Bybit en
  `core/backtest.py` (`--costs bybit`=5.5+2bps / `bybit_cons`=5.5+10bps, funding
  devengado por settlement) + motor `strategies/funding_extreme.py` (alias `funding`).
  Edge standalone BUENO (bybit: PF 1.44, expectancy +30bps, maxDD SOLO 12.96%) pero
  como PROP **RECHAZADO**: gate bybit_cons two-step 27.1% pass / 36.7% breach (vs
  >=60%/<=20%), peor que E9. N2->N4 agota el alfa no-indicador barato. Cierre formal
  del plan B depende SOLO de N0. **N0-lite publico ejecutado 2026-07-04** con
  `tools/bybit_public_cost_probe.py`: 12 snapshots Bybit BTCUSDT perp, ordenes 1k/3k/6k/
  12.5k/25k; spread p95 0.016bps, profundidad p50 dentro de 1bp ~703k USDT lado debil,
  coste taker total p95 5.51-5.54bps. Resultado: el supuesto barato `bybit` queda
  defendible para tamanos E9, pero NO sustituye fills reales ni funding. N0 formal sigue
  pendiente si se quiere operar: testnet/mainnet/Hyro para API, fills, funding y reglas.
  Costes reales <=7bps reabren E9 one-step; >=12bps = cierre sin apelacion.
  **E9+funding medido 2026-07-04**: PropSwing cacheado + `model_funding`; tests 125/125.
  Hyro 2018-26 bybit two-step 68.9% pass / 24.1% breach; bybit_cons 68.1/26.3.
  2020-26 bybit 57.6/32.1; bybit_cons 60.3/36.2. Reabre estadisticamente pero NO go:
  breach >20% y 2024-26 aislado malo (-7.4%, one-step 4.3%, two-step 0%). Comparativa:
  Breakout descartado para E9 (daily 3% -> breach 41-61%); CFT two-phase es mejor
  rule-set (2018 73.7/22.3, 2020 64.1/30.0) pero aun breach alto y Bybit personal
  mantiene riesgo jurisdiccional. **Frontera parcial riesgo/notional 2026-07-04**:
  auditoria Hyro two-step muestra que los fallos son `breach_total`, concentrados en
  inicios 2023-25 (2018-22 pasa 100%); no es daily ni trade-loss. Celdas 2018 que
  parecian buenas no validan 2020: r0.75/n0.5 CFT 53.9/16.8 e Hyro 46.1/18.8;
  r1.0/n0.4 CFT 59.9/26.5 e Hyro 57.7/26.5. No hay celda >=60% pass y <=20% breach
  en 2020. **Phase-router probe 2026-07-04** (`tools/prop_phase_matrix.py`): E9 bajo
  CFT mejora mucho si SOLO se compra challenge en `bear_onset|accumulation` y se evita
  `post_halving|bull_peak`. E9 CFT 2020-26 combinado bear+accum = 74.5% pass / 16.8%
  breach; 2018-26 = 85.0% / 9.8%. **Router real ejecutado**: `PropSwingConfig`
  recibe `entry_halving_phases` (default vacio, reversible); candidato CFT-only
  `risk_per_trade=0.018`, `max_notional_pct=0.8`, `entry_halving_phases="bear_onset,accumulation"`,
  `bybit_cons`: 2020-26 74.8% pass / 2.0% breach / 23.2% timeout; shift -60 = 74.2/16.0;
  shift +60 = 75.5/0.0. 2018-26 default 72.2/5.1; shift -60 71.9/13.9; shift +60
  71.5/5.1. Tests 125/125. Hyro queda FUERA: mismo candidato 2020 74.7/24.7,
  2018 62.2/24.4 + trade_loss violations. Siguiente: validar rules reales CFT/Match/MT5
  y si CFT permite senales propias/manuales; sin confirmacion escrita, no comprar.
  **Operativa Prop/CFT preparada 2026-07-05**: sin tocar alfa, `PropSwing` persiste estado
  live/paper (`pos`, dia, funding idx) en BotState `prop_swing`, escribe journal
  `data/runtime/prop_live_journal.jsonl`, monitor CFT en `core/cft_monitor.py` con estado
  `data/runtime/prop_cft_status.json`, hard-stop si entra en zona CFT, comandos Telegram
  `/prop` `/prop_report` `/prop_pause` `/prop_resume`, check diario y setup VM
  `deploy/setup_prop_cft_paper.sh`. Tests completos: 132/132.

---

## ESTADO ACTUAL

**DEFAULT VIGENTE: Swing Allocator v5 post-audit (2026-07-02, sesion 16) — CONGELADO.**
v5 = v4 estructural + `daily_on_closed_only=True` (F8, unico delta de comportamiento; el resto
del plan F1-F19 son motor/metricas/operativa live). Anclas v5 (dataset canonico 102931):
- 2015-26 realistic: $9.137M | CAGR +85.84% | Max DD -52.73% | 70 rebalanceos | btc_vs_bnh 0.8171
- 2018-26 realistic: $219.8k | CAGR +47.14% | Max DD -53.72% | 53 rebalanceos | btc_vs_bnh 0.8432
- 2015-26 conservative: $8.897M | CAGR +85.40% | Max DD -52.88% | 70 | btc_vs_bnh 0.7961
Coste del fix anti-lookahead vs v4: -0.27pp CAGR / -0.02pp DD — adoptado por higiene, no resultado.
Rollback exacto a v4 congelado: `--config '{"daily_on_closed_only": false}'`. Tests 88/88 verde.
NOTA (2026-07-03): estas anclas son RUTA-TOOL (`tools/swing_v5_freeze_report.py`). El CLI
(`main.py backtest`) da $9.164M / +85.9% en 2015-26 realistic — NO es regresion: difiere la
contabilidad del warmup (CLI analiza 96930 velas, tool 96907; 23 velas en el tramo 2014 con
huecos), desplaza el INIT y desvia la valoracion USD +0.29%. DD/ratio/rebalanceos identicos.
Smoke por CLI debe comparar contra $9.164M; smoke por tool contra $9.137M exacto.
Auditoria post-implementacion: `AUDITORIA_SWING_V5_POST_IMPLEMENTACION.md`. CONGELADO en tag
`swing-v5-frozen` @ 4c955fb (2026-07-02).

**FOCO UNICO: Swing Allocator.** Pro Trend queda PAUSADO INDEFINIDAMENTE (decision 2026-07-01,
sesion 14). No se continua ni paper trading ni optimizacion por ahora. El codigo queda como esta
(v13, congelado y reversible). Retomable en el futuro, pero fuera del roadmap activo.

**Pro Trend v13** (CONGELADO — no se continua). Framework de validacion estaba COMPLETADO.
- 2018-2026 realistic: +521.84% / CAGR +25.7% (partial_exit=150%) vs B&H +550% / +26.4%.
- 2015-2026 realistic: +5812% / CAGR +44.9% — 3 ciclos bull validados.
- Ventaja real: riesgo, no retorno. 35% tiempo en mercado, evita crashes -70%.

**Swing Allocator v4** (2026-07-01, sesion 14 — SUPERSEDIDO por v5, ver arriba; v4 sigue siendo
la referencia estructural congelada en tag `swing-v4-frozen`). Paso go/no-go completo.
- Cambio v3->v4: `min_btc_pct` 0.30->0.20 y `delta_bear_onset` -0.20->-0.30. Resto de v3 intacto
  (regime_off_on_bear_onset=True, bull_peak_ema50_cap=0.85). Mejora AMBAS anclas a la vez.
- Mecanismo estructural: el floor 0.30 clampeaba y bloqueaba el estado de bear profundo (las senales
  nunca calculan <0.20). Bajarlo desbloquea "mas USDT en bear -> recompra mas barata" = la tesis central.
- 2015-2026 realistic: CAGR +86.2% / Max DD -52.71% (v3: 82.4% / -53.64%) → +3.8pp / -0.9pp.
- 2015-2026 conservative: +85.7% / -52.86%. 2018-2026 realistic: +47.6% / -53.42% (+4.6pp CAGR).
- WF 4/4 TEST positivo (CAGR 21.5/41.5/20.8/82.4%, PF>1.8). ETH inerte (cambios BTC-especificos) ✅.
- Rollback: `--config '{"min_btc_pct": 0.30, "delta_bear_onset": -0.20}'` vuelve a v3.
- DD residual reordenado: max ahora 2019->COVID (-53%) y flash-crash mayo-2021 (-50%). ~50-52% es el
  suelo estructural de long-only 100% en mercado — NO perseguir (rompe tesis o cuesta CAGR, ver latch).

**HECHO (sesion 15, 2026-07-02):**
- **Smoke-verify v4 OK**: `backtest --strategy swing 2015-2026 realistic` reproduce CAGR +86.2% /
  Max DD -52.71% / 68 rebalanceos / 96930 velas analizadas. Las 5 metricas nuevas se muestran
  (Median trade +602 legacy, Calmar 1.63, DD duracion 260d, Sharpe 1.38, Sortino 1.57).
- **Cache 102931 ADOPTADO como canonico** (decision 2026-07-02): BTC-USDT_1H 2014-04-25 → 2026-01-01,
  continuo, cero huecos >24h. Reemplaza al viejo de 96906. v4 validado sobre el (WF 4/4, ETH inerte,
  smoke OK). El PF legacy 4.43 era artefacto de pairing; tras F1 el PF ACB del smoke es 88.38,
  confirmando que PF/WR/expectancy siguen siendo metricas contables de rebalanceos, NO anclas de
  decision. Anclas siguen siendo CAGR/DD/Calmar y BTC vs B&H.

**HECHO (sesion 15 bis, 2026-07-02): v4 commiteado y CONGELADO** (tag `swing-v4-frozen` @ 06395ff).
Auditoria completa en `AUDITORIA_SWING_V4.md`; plan de ejecucion en `PLAN_MEJORA_AUDITORIA.md`
(en curso, ver checkboxes alli).

**HECHO (sesion 16, 2026-07-02): F1-F4 parciales cerrados.**
- F1: `_compute_trade_pnl_acb` con coste medio ponderado, fees prorrateados y selector interno
  `trade_pnl_method="acb"|"legacy_fifo"`. Tests: `python -m pytest tests/test_backtest_pnl.py -q` = 6/6.
- F2: `underwater_days` real (peak->recovery) junto a `max_dd_duration_days` (peak->trough).
- Smoke v4 post-F1/F2: final $9.307M, CAGR +86.2%, Max DD -52.71%, 96930 velas, underwater 922d.
  Equity sin cambios; solo cambian metricas por rebalanceo.
- F3: README y CLI dejan de presentar PF del Swing como veredicto.
- F4: umbrales de fase de halving parametrizados (`phase_post_end/phase_peak_end/phase_onset_end`)
  con defaults 180/540/900; smoke default reproduce anclas.
- F5: matriz calendario completa sobre v4 congelado. El signo del edge sobrevive en todas las
  variantes, pero el reloj sigue fragil: shift -60d baja CAGR a +72.86%; shift +60d sube DD a -66.08%.
- F6: `halving_only` extra RECHAZADO como simplificacion. 2018 realistic: +41.66% CAGR / -50.91%
  DD / `btc_vs_bnh=0.6410` vs v4 +47.59% / -53.42% / 0.8641. Conservative 2015: +73.56% /
  -50.91% / 0.4004 vs v4 +85.65% / -52.86% / 0.8082. Mantener `use_regime=True`.
- F7: bootstrap mensual v4 congelado x1000: MaxDD p50 -53.01%, p95 -68.31%, p99 -74.34%;
  sizing futuro debe usar p95/p99, no el -52.7% historico.
- F8: `daily_on_closed_only=True` ADOPTADO por higiene anti-lookahead. Impacto aislado: CAGR
  +85.84% vs +86.11%, DD -52.73% vs -52.71%. Rollback: `--config '{"daily_on_closed_only": false}'`.
- F9: `clock_aligned_cadence=True` MEDIDO y NO adoptado. Empeora CAGR a +84.62% y no reduce
  sensibilidad al offset 2015-01-02.
- F10: `fill_next_open` medido y NO adoptado como default: impacto despreciable (+86.08% vs +86.11%,
  DD igual). Se mantiene para mediciones en `BacktestClient(fill_next_open=True)`.
- F11: B&H ahora incluye coste de compra; `lookback_hours` documenta que EMA200D es truncada.
- F12: `OKXClient.get_ohlcv` pagina hasta `limit` y devuelve `timestamp` ms `int64`, igual que
  `BacktestClient`. Smoke OKX real: 6000 filas 1H / dtype int64.
- F13: ruta `start` ya instancia Swing y pasa `RiskManager`; Swing bloquea compras si
  `check_daily_loss()` dispara, pero permite ventas defensivas. NO se ejecuto `start` (requiere OK
  explicito y 24h para cerrar operativo).
- F14: controles minimos Swing paper/live: rechazo de tick anomalo (`max_price_jump_pct=0.25`),
  OHLCV insuficiente bloquea decisiones live, `main.py stop` es kill switch, rebalanceos live/paper
  se persisten en `data/runtime/swing_rebalances.jsonl`.
- F16: stress USDT depeg current default. Depeg -10% en 2018-06: CAGR +84.37%, final $8.37M.
  Depeg -10% en 2022-06: CAGR +84.30%, final $8.34M. Riesgo aceptable en backtest, pero capital
  estable/custodia siguen siendo riesgo real.
- F17 sizing formal: dimensionar con MaxDD p95/p99 bootstrap (-68%/-74%), no con -52.7% historico.
  Conservador 10-20% del patrimonio cripto; moderado 30-50%; agresivo solo si sustituye el sleeve BTC
  completo y se acepta DD tipo -75%. Sin apalancamiento; limitar custodia concentrada en un exchange.
- F15 parcial: `tools/swing_parity_check.py` compara target live/backtest con las mismas 6000 velas.
  Check puntual OK 2026-07-02 12:00 UTC: ambos target 0.2000, `regime_bear;halving_bear_onset`.
  Cierre real sigue siendo 30 dias de paper sin divergencias.
- F18 parcial: `tools/swing_benchmarks.py` implementa benchmarks Swing. 2015-2026 realistic current:
  Swing $9.14M / CAGR +85.84% / DD -52.73%; 60/40 mensual $540k / +43.71% / -65.01%;
  EMA200D long/flat $1.47M / +57.36% / -74.93%; DCA semanal $539k / +43.69% / -79.06%.
  Falta integrar estos benchmarks en `main.py baselines`/README.
- F19 parcial: `tools/degradation_report.py` lee `data/runtime/swing_rebalances.jsonl` y alerta por
  frecuencia >2x backtest o gap target/after >2pp. Sin datos live aun (`no_data` esperado).

**Descartado sesion 14 (no reintentar):** latch del cap (`bull_peak_cap_latch`), regime_delta 0.15,
VIX, MVRV (wash), Pi Cycle (inerte), floor <0.20 (inerte, senales nunca bajan de 0.20).

**Descartado sesion 15 (no reintentar): cap-target con `bear_onset` activo.** Ataca la fase
equivocada. Evidencia empirica (journal v4 2015-26, target medio por fase temporal del halving):
post_halving 0.89 | **bull_peak 0.91** | **bear_onset 0.30** | accumulation 0.63. El Max DD nace en
bull_peak (techos 2013/17/21-abr/25 + flash-crash mayo-21) y accumulation (COVID @0.63), NO en
bear_onset — que dispara a 540d, cuando el crash del techo ya paso y el delta -0.30 ya bajo el target
a 0.30. Un cap sobre bear_onset ataria en 1 de 8 rebalanceos = overfit de 1 evento.

**FRENTE DE MAX DD CERRADO (sesion 15).** El -52.71% (v4) es el suelo estructural de long-only ~100%
en mercado. Todo lever probado o agota CAGR o es inerte: global max_btc_pct cap (mata CAGR), latch
(-4.6pp CAGR), floor<0.20 (inerte), bear_onset cap (inerte). Unico lever no explorado = de-risk
intradia por spike ATR para crash tipo-COVID; DESCARTADO por diseno (rediseno mayor, overfit sobre 1
evento, probable coste de CAGR en whipsaws). No perseguir mas DD. Proximo hito Swing = validacion
forward / paper trading, no mas optimizacion de backtest.

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

### 5. Out-of-sample — ventana 2015-2026 CERRADA para optimizacion (auditoria 2026-07-02)
- Ningun cambio de estrategia se adopta por mejorar 2015-2026. Esa ventana solo se usa para MEDIR
  robustez/sensibilidad de lo ya adoptado. La evidencia para cambios futuros = datos posteriores a
  2026-01-01 (forward/paper) o justificacion estructural pura + no-empeora-anclas.
- Excepcion permitida: SIMPLIFICACION (quitar componentes) si no empeora las anclas.
- v4 congelado en tag `swing-v4-frozen` (commit 06395ff).

### 4. Determinismo de datos
- Backtests deterministas via cache OHLCV (`data/cache/`). Runs con rango cacheado = velas identicas.
- Resultado SENSIBLE al punto de inicio (dataset canonico: 102931 velas, adoptado 2026-07-02; viejo 96906). No mezclar caches entre maquinas.
- Backtests CONTINUOS — nunca reiniciar balance en frontera de año/mes.

---

## SIGUIENTE PASO — Swing Allocator (foco unico)

Pro Trend pausado. **Optimizacion de backtest del Swing = CERRADA** (v5 post-audit default, frente
de Max DD agotado, ver arriba). El proximo hito NO es mas backtest: es **validacion forward /
paper trading** del Swing v5 (cierra F13 24h + F15 paridad 30d + F19 datos de degradacion).
`start` en vivo requiere confirmacion explicita.

**HECHO (sesion 16 bis, 2026-07-02): fixes de la ruta live/paper (post-freeze, no tocan senales).**
Al preparar el arranque del paper se detecto que la ruta live NO funcionaba: el scheduler de
`start` re-instancia la estrategia en cada tick y el Swing no persistia estado → tras el INIT
nunca volvia a rebalancear; ademas el balance paper vivia en memoria (reinicio = portfolio a $10k)
y `bot add` no aceptaba swing. Fixes aplicados:
- Estado live del Swing persistido en BotState fila ("swing_allocator", symbol, is_active=False),
  mismo patron que Pro Trend: `initialized`, `last_rebalance`, `last_eval_block`.
- Cadencia live = UNA evaluacion por bloque 4H UTC (persistida; robusta a restarts y a cualquier
  tick). Si los datos de mercado fallan, el bloque NO se consume (reintento al siguiente tick).
  Backtest mantiene su cadencia exacta `_bar_count % 4` (sin cambio de comportamiento).
- Balance paper persistido en `data/runtime/paper_state.json` (opt-in via `_make_client`; los
  tests no tocan disco). Limit orders pendientes NO sobreviven restart (el Swing solo usa market).
- `bot add swing BTC-USDT` funciona; filtro tick-anomalo (F14) ahora SOLO live/paper (resuelve M2
  de la auditoria v5). Ancla 2015-26 realistic re-verificada identica. Tests 96/96.
Paper listo para arrancar: `python main.py bot enable swing_allocator_btc_usdt BTC-USDT` +
`python main.py start` (requiere OK explicito y proceso vivo; reinicios ya no pierden estado).

**HECHO (sesion 18, 2026-07-04): PAPER DESPLEGADO — VM GCP e2-micro us-central1 (free tier),
Debian 13, VM `matitrbot`.** Servicios verdes, INIT 0%->60% + SELL 60%->20% @ $62,573
(regime_bear,halving_bear_onset — coincide con parity F15). Smoke F13 corre desde
2026-07-04 08:58 UTC; 30 dias de paridad empiezan al superarlo. Fixes del deploy:
DetachedInstanceError en `bot enable/disable` (9214e1e), cron vacio por `set -e` + pipe sin
crontab previo en `install_vm.sh`, y 403 de Cloudflare OKX al UA de urllib (`fetch_price`).
Control remoto Telegram AMPLIADO (a15c8e2): watchdog sin-tick push, heartbeat diario 08:00 UTC,
backup semanal automatico al chat, /equity /chart (PNG matplotlib lazy, `tools/tg_charts.py`),
/signals /parity /health /logs /backup /restart /update (sudo -n; GCP google-sudoers),
setMyCommands, HTML + fallback texto plano. Todo verificado en produccion. Estado y runbook:
`DEPLOY_PAPER.md`. Operacion normal = leer heartbeat 08:00 + check 12:10; consola innecesaria.

**HECHO (sesion 16 ter, 2026-07-02): infra cloud para el paper — plan aprobado por Matias.**
El paper correra en VM gratuita (Oracle Free / GCP e2-micro) con control remoto por Telegram.
**Runbook completo y ESTADO DEL DESPLIEGUE en `DEPLOY_PAPER.md`** (ese doc es el punto de
reanudacion si esto se pausa). Piezas: `tools/telegram_remote.py` (/status /report /pause
/resume + alertas de rebalanceo, long-polling sin puertos), `tools/tg_send.py`,
`deploy/install_vm.sh` + units systemd (Restart=always) + `daily_checks.sh` (cron 12:10 UTC:
paridad F15 + degradacion F19, alerta si PARITY_FAIL). Los 11 tools con ROOT hardcodeado
Windows ahora son portables a Linux. `.env` en VM: OKX_SANDBOX=false (datos reales; el demo
romperia paridad) + TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID. Pendiente de Matias: cuenta cloud
y bot de @BotFather. data/runtime/ y trading.db gitignored.

**HECHO (sesion 14):**
- Auditoria del cap `bull_peak_ema50_cap_*`: 24 disparos en 2015-26, TODOS SELL 100%->85%, en los 3
  techos (2017:9, 2021:5, 2024-25:10). Estructural, NO overfit a un evento. PERO casi todos en PARES
  (btc_pct_before=0.9997 siempre) => es ping-pong sell-85%/rebuy-100% en el techo. Feb y Ago 2025 =
  3 ventas cada uno. El cap solo aporta 1.6pp de Max DD (v2 -55.23 -> v3 -53.64).
- **Latch del cap PROBADO Y DESCARTADO.** `bull_peak_cap_latch` mantiene el cap hasta cambio de fase.
  Mecanismo OK (24->3 disparos) pero PEOR: dispara early y handcuffea a 85% todo el rally
  (2017 $827->$19k). 2015 realistic CAGR 81.39->76.8% (-4.6pp), DD ni mejora (-53.64->-54.02).
  Conservative 80.93->76.5%. El rebuy-a-100% de v3 era CORRECTO. Q4 2025 mejora aislado = overfit.

**Candidatas para Max DD: TODAS descartadas (frente cerrado sesion 15).** Ver bloque "FRENTE DE
MAX DD CERRADO" arriba. cap-target-on-bear_onset (inerte, fase equivocada), latch, floor<0.20,
global caps, ATR intradia — todas agotan CAGR o son inertes. NO reabrir sin evidencia nueva.

Regla dura (si algun dia se reabre): candidato se compara por CAGR y Max DD (anclas), PF como rango,
inicio 2015 fijo, AISLADO vs baseline v4.

---

## PENDIENTES ABIERTOS

- **Q4 2025 (Swing):** ping-pong estructural residual. Sin via viva (cap-bear_onset descartado sesion 15).
  Descartados: cooldown=7d, ADX gate. Detalle en SESSION_ARCHIVE.md ("Q4 2025 mitigacion"). NO reabrir.
- **Max DD Swing (-52.71% v4):** FRENTE CERRADO (sesion 15). Es el suelo estructural de long-only.
  Nace en bull_peak (target medio 0.91) y accumulation/COVID (0.63), NO en bear_onset. Ver bloque
  "FRENTE DE MAX DD CERRADO". No perseguir.
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
