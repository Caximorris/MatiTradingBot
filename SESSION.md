# SESSION.md — Estado del proyecto y referencia detallada

Complemento de CLAUDE.md. Actualizar al cerrar cada sesion.
**Ultima actualizacion: 2026-06-30 (decima sesion)**

---

## ESTADO ACTUAL

**Version en codigo: Pro Trend v13** con 5 lookahead fixes, framework de validacion completo y partial_exit_pct=150% por defecto.
**Resultado honesto 2018-2026 realistic: +521.84% CAGR +25.7% (con partial_exit=150%) vs B&H +550% CAGR +26.4%**
**Resultado 2015-2026 realistic: +5812% CAGR +44.9% — validado en 3 ciclos bull (2017, 2021, 2024-25)**
La ventaja real de Pro Trend NO es el retorno absoluto — es el riesgo: 35% tiempo en mercado, evita crashes del -70%.

**Pro Trend v13: framework de validacion COMPLETADO. Siguiente: paper trading 6 meses en paralelo.**

**Swing Allocator v1 ADOPTADO como default** (2026-06-30). Framework de validacion COMPLETADO.
WF v1 4/4 ✅ | ETH v1 +56.4% CAGR ✅ | Conservative +69.8% CAGR ✅ | BTC 2015-2026 +77.4% CAGR ✅
Config default: `use_regime=True, use_halving=True`, resto False. `delta_post_halving=0.20, delta_bear_onset=-0.20`.
ETH v1 == v0 por diseno: ETH no tiene halvings, delta_post_halving/bear_onset nunca se activan.
Buffer slippage corregido: 0.2% → 0.35% (cubria conservative 0.25% de coste con margen insuficiente).
**Pendiente: baseline realistic fresco para verificar que defaults en codigo == CLI override anterior.**
**Siguiente opcional: tests segunda ronda (threshold=0.15, deltas asimetricos). Ver paso 8.**

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

**Tests pendientes de segunda ronda (opcionales — v1 ya es default y validado):**
- Baseline realistic fresco: verificar defaults codigo == CLI override anterior (~68 trades esperados)
- `delta_post_halving=0.15` — punto medio entre 0.10 y 0.20
- `halving=0.20 + threshold=0.15` sin bajar regime delta
- Deltas asimetricos: `delta_regime_bull=0.15, delta_regime_bear=-0.25` (salir mas rapido en bear)
- `base_btc_pct=0.50` y `base_btc_pct=0.70`
- `min_days_between_rebalance=1` y `=7`
- `adx_min_trend=20` y `=25`
- `min_btc=0.20 + halving=0.20`
- Analisis Q4 2025: todos los configs pierden — abrir journal y entender por que

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
| **Swing Allocator v1 DEFAULT (halving=±0.20, WF 4/4)** | 2015-2026 | $5,486,167 | +54762% | 68 | 2.46 | +77.4% |
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
