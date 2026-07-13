# EXPERIMENTS.md — Registro de experimentos

Plan T11.1 (`docs/forward-test/research-lab-plan.md` §11). Un solo lugar para no repetir una
idea ya descartada. Antes de proponer un cambio de estrategia, `Ctrl+F` aqui primero.

Historia detallada anterior a este registro (2026-06 a 2026-07-06) vive en
`docs/archive/session-archive.md` y `docs/swing/audits.md` — este archivo consolida el
resultado, no la narrativa completa.

## Como anadir una entrada

Copiar el bloque, rellenar, anadir a la seccion que corresponda (Aceptado/Rechazado/Parqueado).

```
### EXP-NNN — <titulo corto>
- Fecha:              YYYY-MM-DD
- Estrategia:          swing | pro_trend | prop_swing | motor de backtest
- Hipotesis:           <una frase>
- Ventana de datos:     2015-2026 | 2018-2026 | forward (post 2026-01-01)
- Metricas:             CAGR X% | Max DD Y% | btc_vs_bnh Z | PF (rango, no ancla)
- Decision:             accepted | rejected | parked
- Razon:                <por que>
- Permitido en forward-test?: yes | no (ver docs/forward-test/contract.md)
- Referencias:          commit/branch, journal o reporte
```

---

## Aceptado (default vigente)

### EXP-001 — Swing v2: regime_off_on_bear_onset
- Fecha: 2026-07-01
- Estrategia: swing
- Hipotesis: suprimir SOLO regime_bull durante bear_onset arregla el ping-pong de Q4 2025 sin tocar regime_bear.
- Ventana de datos: 2015-2026 y 2018-2026
- Metricas: 2015-26 +80.6% CAGR / -55.23% DD (vs v1 78.4%/-57.60%); 2018-26 +41.5%/-53.42%; WF 4/4 test positivo; ETH identico a v1.
- Decision: accepted (default)
- Razon: mejora ambas anclas en ambas ventanas, reversible por config.
- Permitido en forward-test?: yes (es el default)
- Referencias: `docs/swing/plan.md`, SESSION.md

### EXP-002 — Swing v5: daily_on_closed_only
- Fecha: 2026-07-02
- Estrategia: swing
- Hipotesis: evaluar indicadores diarios solo con dias UTC cerrados (F8 de la auditoria v4) no cambia el resultado si no habia lookahead, y lo confirma.
- Ventana de datos: 2015-2026 y 2018-2026
- Metricas: 2015-26 realistic $9.137M / +85.84% CAGR / -52.73% DD / 70 reb (tool `swing_v5_freeze_report.py`); CLI da $9.164M (warmup distinto, no regresion).
- Decision: accepted (default historico, ahora rollback/control; tag `swing-v5-frozen`)
- Razon: unico delta de comportamiento vs v4 estructural; preservado como baseline v5.
- Permitido en forward-test?: yes (control/rollback de v6-2)
- Referencias: tag `swing-v5-frozen` @ 4c955fb, `docs/swing/audits.md`

### EXP-006 — Swing v6-2: funding overlay +0.05
- Fecha: 2026-07-13
- Estrategia: swing (v6)
- Hipotesis: overlay de funding moderado (+0.05, ttl 7d, accumulation, p10/p90) mejora recompra sin exceso de churn.
- Ventana de datos: 2015-2026, 2018-2026, realistic/conservative y rolling starts
- Metricas: 2015-26 realistic $9.505M / +86.51% CAGR / -52.73% DD / 0.8499 BTC ratio; 2018-26 $229.0k / +47.90% / -53.72% / 0.8785; conservative $9.255M / +86.06% / -52.88% / 0.8281.
- Decision: accepted (default congelado)
- Razon: domina las tres anclas, mejora 7/8 rolling starts y no empeora DD, churn ni BTC final. El usuario aprobo la excepcion porque v5/v6 iniciaron paper simultaneamente; no autoriza live.
- Permitido en forward-test?: yes; mantener v5 aislado como control/rollback
- Referencias: `docs/swing/v6-plan.md` §6, `SESSION.md`

### EXP-003 — Pro Trend v13: partial_exit_pct=150.0
- Fecha: 2026-06-30
- Estrategia: pro_trend
- Hipotesis: vender 33% de la posicion cuando la ganancia supera 150% mejora CAGR sin empeorar DD.
- Metricas: +1pp CAGR, mejor PF, DD neutro.
- Decision: accepted (era el default hasta el freeze; congelado en v13)
- Razon: confirmado por backtest aislado.
- Permitido en forward-test?: n/a (Pro Trend pausado, no esta en forward-test)
- Referencias: `docs/archive/session-archive.md`

---

## Rechazado — NO reintentar sin evidencia nueva

Filtros de senal del Swing (sensitivity, 2026-07-02): **MVRV, Pi Cycle Top, RSI, VIX, MACD 4H**
— los cinco quedan con `use_*=False` en default. No reabrir sin dato forward nuevo.

Frontera de Max DD del Swing (sesion 15, CERRADA): **latch del cap de bull_peak, regime_delta
0.15, floor `min_btc_pct<0.20`, cap global de `max_btc_pct`, ATR intradia, `halving_only`,
`clock_aligned_cadence`, `fill_next_open`** — todo lever probado agota CAGR o es inerte. Suelo
estructural de long-only ~100% en mercado.

Ping-pong Q4 2025 (residual estructural, sin via viva): **cooldown=7d, ADX gate, cap-bear_onset**
— descartados individualmente, arreglado en cambio por EXP-001 (v2) sin volver a estos levers.

Swing v6 — no testear de entrada (`docs/swing/v6-plan.md` §6): **`min_btc_pct=0.0`** (ya
descartado como default por BTC final), **caps globales de `max_btc_pct`** (matan CAGR),
**latch del bull peak cap** (descartado), **suprimir todo regime en bear_onset** (descartado),
**shorts o perps dentro de Swing** (fuera de tesis).

### EXP-004 — Swing v6-3: funding overlay +0.10
- Fecha: 2026-07-06
- Estrategia: swing (v6)
- Hipotesis: overlay de funding mas agresivo (+0.10, ttl 7d, accumulation, p10/p90) mejora recompra.
- Decision: rejected
- Razon: exceso de churn vs V6-2 sin mejora proporcional.
- Permitido en forward-test?: no (nunca fue default)
- Referencias: `docs/swing/v6-plan.md` §6

### EXP-005 — Prop/CFT: funding_extreme como estrategia prop firm
- Fecha: 2026-07 (ver `docs/prop/hyrotrader-plan.md`)
- Estrategia: prop_swing / funding_extreme
- Hipotesis: el motor `funding_extreme` (edge standalone real: PF 1.44, DD 13%) pasa el gate two-step de una prop firm tipo CFT/Hyro.
- Metricas: ~27% pass rate / ~37% breach rate en el gate two-step simulado (umbral requerido >=60% pass / <=20% breach).
- Decision: rejected (como producto prop firm; el motor standalone sigue siendo valido como hallazgo)
- Razon: no cumple el gate de evaluacion de dos fases.
- Permitido en forward-test?: no
- Referencias: `docs/prop/hyrotrader-plan.md`

---

## Parqueado — needs more validation / bloqueado en prerequisito

### EXP-007 — Swing v6-4/5/6: variantes bear accumulation, bull peak neutral, chop guard
- Fecha: pendiente
- Estrategia: swing (v6)
- Hipotesis: V6-4 (accumulation bear target 0.30/0.35), V6-5 (bull peak neutral 0.75), V6-6 (chop guard solo diagnostico) — ver matriz completa en el plan.
- Decision: parked (pendiente de ejecutar)
- Razon: prioridad P2/P3, no bloquea nada del paper actual.
- Permitido en forward-test?: no (no ejecutado aun)
- Referencias: `docs/swing/v6-plan.md` §6

### EXP-008 — Pro Trend: fix MACD 4H key
- Fecha: pendiente
- Estrategia: pro_trend
- Hipotesis: bug candidato en la clave usada para el contexto MACD 4H (P1, sin backtest aislado).
- Decision: parked
- Razon: Pro Trend esta PAUSADO INDEFINIDAMENTE; no se toca `pro_trend.py` sin decision explicita de reanudar.
- Permitido en forward-test?: n/a
- Referencias: SESSION.md "PENDIENTES ABIERTOS"

### EXP-009 — Pro Trend: fix VIX sizing cap
- Fecha: pendiente
- Estrategia: pro_trend
- Hipotesis: bug candidato en el cap de sizing por VIX (P1, sin backtest aislado).
- Decision: parked
- Razon: idem EXP-008.
- Permitido en forward-test?: n/a
- Referencias: SESSION.md "PENDIENTES ABIERTOS"

### EXP-011 — funding_extreme como vehiculo propio (sin limites prop)
- Fecha: 2026-07-13 (pre-registrado)
- Estrategia: funding_extreme
- Hipotesis: quitar el corse prop (limites diarios del challenge) y ajustar risk_per_trade
  recupera CAGR manteniendo el perfil de DD bajo (~13%) -> candidato a "pata de ingresos".
- Ventana de datos: 2020-06 -> 2026-01 (Bybit funding empieza 2020-03) + OOS 2026-01 -> hoy.
- Metricas (EJECUTADO 2026-07-13, 5 runs de 6):
  - A0 sanity (bybit, risk 1%): +72.73% | CAGR 10.3% | DD -12.96% | PF 1.44 | 238 tr. Reproduce §15.
  - A1 sin limites prop (risk 1%): IDENTICO a A0 al centimo — los limites nunca muerden a 1%.
  - A2 risk 2% (bybit): +115.88% | CAGR 14.8% | DD -15.06% | PF 1.42 | Calmar 0.98. GANADOR.
  - A2b risk 2% sin limites: +116.22% | DD -16.05% — los limites recortan algo el DD; dejarlos.
  - A3 risk 2% (bybit_cons): +84.08% | CAGR 11.5% | DD -16.58% | PF 1.32. Sobrevive.
  - Mensual (tools/monthly_dist.py, A2): media +1.23%/mes, mediana +0.90%, 60% meses
    positivos, peor mes -7.1%, racha max 3 meses negativos. (~$123/mes sobre $10k.)
- Decision: parked (gate: CAGR 14.8% vs >=15% requerido — fallo marginal de 0.2pp; DD, PF cons
  y % meses positivos cumplen. Falta A4 (OOS 2026), BLOQUEADO: correr post-2026-01 mutaria el
  cache OHLCV canonico (incidente 2026-07-06). Decision de adopcion pendiente de Matias.)
- Razon: plan completo, gates y resultados en `docs/income/plan.md` (Via A).
- Permitido en forward-test?: no (nunca default; paper propio solo si pasa gate + OK explicito)
- Referencias: `docs/income/plan.md`, `docs/prop/hyrotrader-plan.md` §15

### EXP-012 — MR-Regimen 1H (mean reversion condicionada por regimen macro)
- Fecha: 2026-07-13 (pre-registrado)
- Estrategia: nueva (`strategies/mr_regime.py`, no existe aun)
- Hipotesis: los dips bruscos 1H revierten SOLO en regimen macro alcista (EMA50D>200D +
  close>200D + ADX14D>15, dia cerrado); el edge es el condicionamiento, no el oscilador.
  (mean_reversion sin condicionar ya fallo y se borro — esta es la variante condicionada.)
- Ventana de datos: IS 2019-2024 / OOS single-shot 2024-2026-01 / forward paper si pasa.
- Metricas: pendiente. Gates IS: PF>1.2, >=150 trades, DD<25%. OOS: PF>1.1, DD<30%.
- Decision: parked (pre-registrado; presupuesto 8 variantes IS, rejilla cerrada en el plan)
- Razon: pre-registro completo (senal, split, gates, kill criteria) en `docs/income/plan.md` (Via B).
- Permitido en forward-test?: no (bot aislado nuevo solo si pasa gates + OK explicito)
- Referencias: `docs/income/plan.md`

### EXP-010 — Prop: router CFT-only (entry_halving_phases=bear_onset,accumulation)
- Fecha: ver `docs/prop/hyrotrader-plan.md`
- Estrategia: prop_swing
- Hipotesis: restringir entradas a fases bear_onset+accumulation es el mejor candidato prop encontrado hasta ahora.
- Decision: parked (bloqueado en prerequisito externo)
- Razon: requiere validar reglas reales CFT/Match/MT5 con confirmacion ESCRITA antes de cualquier compra. Sin eso, NO comprar.
- Permitido en forward-test?: n/a (no es una decision de codigo)
- Referencias: `docs/prop/hyrotrader-plan.md`
