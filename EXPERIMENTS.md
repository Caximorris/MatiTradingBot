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
`clock_aligned_cadence`, `fill_next_open`, overlay de riesgo por spike on-chain
(reserva/stablecoin, EXP-015)** — todo lever probado agota CAGR o es inerte. Suelo
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
- Decision: **rejected** (2026-07-14, decision explicita de Matias + analisis comparativo).
  No por el fallo marginal de gate (CAGR 14.8% vs 15%): aun ignorando ese 0.2pp, el motor
  NO compite con Swing v6 en ninguna metrica ajustada a riesgo. Calmar (CAGR/MaxDD):
  Swing v6 2015-26 realistic = 1.64 (86.51%/-52.73%) vs mejor variante funding_extreme = 0.98
  (A2, risk 2%) o 0.96 (cap 1.0 sin leverage); escalar con leverage real (3%/1.5x) DEGRADA
  el Calmar a 0.85. Ninguna configuracion de la frontera de riesgo (ver tabla en
  `docs/income/plan.md`) alcanza el Calmar de Swing. Ademas no es diversificacion real:
  ambos motores son long-only direccional BTC, correlacionados en el tail risk (un crash
  de BTC golpea a los dos). El valor practico de la señal (funding en percentil extremo)
  ya esta capturado con costo marginal casi nulo por `strategies/swing_funding_overlay.py`
  dentro de v6-2 (tilt ±0.05, sin leverage ni infra de perps nueva) — construir un vehiculo
  separado apalancado para el mismo insight, con peor Calmar, es esfuerzo duplicado. Segunda
  vez que este motor se rechaza en un framing distinto (primera vez: prop firm, gate CFT
  two-step 27% pass/37% breach, `docs/prop/hyrotrader-plan.md`). A4 (OOS 2026) NO se ejecuta:
  el plan ya marca OOS aqui como indicativo, no como gate, y no cambia el veredicto.
- Razon: plan completo, gates y resultados en `docs/income/plan.md` (Via A).
- Permitido en forward-test?: no (nunca default; paper propio solo si pasa gate + OK explicito)
- Referencias: `docs/income/plan.md`, `docs/prop/hyrotrader-plan.md` §15
- **CORRECCION 2026-07-14:** los numeros de A0-A3 arriba se calcularon con un bug real
  en `load_funding()` (settlements sin ordenar -> el devengo de funding nunca se aplicaba
  al balance, ver EXP-013). Corregido y re-corrido A2 (risk 2%, bybit): CAGR +12.8% (antes
  14.8%), Max DD -15.22% (antes -15.06%), PF 1.43 (antes 1.42), Calmar 0.84 (antes 0.98).
  El veredicto NO cambia — sigue muy por debajo del Calmar de Swing v6 (1.64) y ahora con
  margen mayor, no menor. La decision "rejected" se mantiene, reforzada.

### EXP-012 — MR-Regimen 1H (mean reversion condicionada por regimen macro)
- Fecha: 2026-07-13 (pre-registrado)
- Estrategia: nueva (`strategies/mr_regime.py`, no existe aun)
- Hipotesis: los dips bruscos 1H revierten SOLO en regimen macro alcista (EMA50D>200D +
  close>200D + ADX14D>15, dia cerrado); el edge es el condicionamiento, no el oscilador.
  (mean_reversion sin condicionar ya fallo y se borro — esta es la variante condicionada.)
- Ventana de datos: IS 2019-2024 / OOS single-shot 2024-2026-01 / forward paper si pasa.
- Metricas (B1+B2 EJECUTADO 2026-07-14, 8/8 runs del presupuesto, `--costs realistic`):

  | entry_mult | stop_mult | hold_h | Trades | Win% | PF   | CAGR   | MaxDD   |
  |-----------:|----------:|-------:|-------:|-----:|-----:|-------:|--------:|
  | 1.5        | 2.5       | 72     | 350    | 53.4%| 0.62 | -11.2% | -46.65% |
  | 1.5        | 3.0       | 72     | 349    | 57.0%| 0.63 |  -9.2% | -39.94% |
  | 2.0        | 2.5       | 72     | 246    | 51.2%| 0.47 | -11.8% | -49.21% |
  | 2.0        | 3.0       | 72     | 246    | 54.9%| 0.50 |  -9.7% | -42.28% |
  | 2.5        | 2.5       | 72     | 158    | 43.7%| 0.39 | -10.5% | -45.26% |
  | 2.5        | 3.0       | 72     | 158    | 49.4%| 0.45 |  -7.6% | -35.07% |
  | 2.0        | 2.5       | 48     | 246    | 51.2%| 0.47 | -11.8% | -49.21% |
  | 2.0        | 3.0       | 48     | 246    | 54.9%| 0.50 |  -9.7% | -42.28% |

  `hold_h` (48 vs 72) produced byte-identical trade counts/PnL at the center entry —
  every trade resolves via reversion or stop before either time-stop binds; the
  parameter is inert for this signal. Mejor PF de las 8: 0.63 (1.5/3.0), lejos de 1.0.
- Decision: **rejected** (kill inmediato per pre-registro: "si hacen falta las 8
  variantes para ver PF > 1 en IS, eso es fitting -> kill" — ni una sola variante
  cruza PF 1.0. B3/B4 (monthly_dist, OOS) no se ejecutan: no hay candidato que
  llevar a OOS, y el pre-registro prohibe gastar el intento OOS sin superar IS).
  Lectura: el condicionamiento por regimen bull NO evita que los dips 1H sigan
  cayendo mas alla de 2-3x ATR14 en las mismas ventanas que ya rompieron
  `mean_reversion.py` sin condicionar (Q3 2019, COVID Q1-Q2 2020, correcciones 2021) —
  el regimen bull diario no filtra los shocks intradia que matan a este detector.
- Razon: pre-registro completo (senal, split, gates, kill criteria) en `docs/income/plan.md` (Via B).
- Permitido en forward-test?: no (bot aislado nuevo solo si pasa gates + OK explicito)
- Referencias: `docs/income/plan.md`

### EXP-013 — Basis Carry (cash-and-carry, market-neutral)
- Fecha: 2026-07-14 (pre-registrado)
- Estrategia: nueva (`strategies/basis_carry.py`)
- Hipotesis: spot BTC long + short sintetico de igual qty (patron `prop_swing.py`) deja
  exposicion neta a precio ~0; el retorno viene solo del funding (Bybit). A diferencia de
  Swing/funding_extreme/mr_regime, esta NO es una apuesta direccional — es diversificacion
  real, no una version mas lenta del mismo riesgo direccional.
- Bug encontrado durante la implementacion: `load_funding()` devolvia settlements SIN
  ordenar (cache en orden de paginacion de API, mas reciente primero) — el puntero
  monotono de `_advance_settle_idx`/`_accrue_funding` (compartido con `funding_extreme.py`
  y `prop_swing.py`) nunca avanzaba, asi que el funding NUNCA se devengaba en ninguna de
  las tres estrategias. Fix en `load_funding()` (ahora `sorted(rows)`), 271/271 suite.
  Ver correccion retroactiva en EXP-011 arriba.
- Metricas (2020-06 -> 2026-01, `--costs bybit`, config default sin ajustar):
  Balance final $47,151 (+371.51%) | CAGR +32.0%/ano | Max DD -1.09% | Calmar 29.36 |
  Sharpe 10.45 / Sortino 67.28 | 9 ciclos, 94.9% tiempo en mercado.
- Decision: **cerrado, no adoptado** (2026-07-14, analisis de concentracion y margen
  completado). Concentracion: MEJOR de lo temido — no es un trimestre con suerte, son
  DOS holds largos (2020-10/2021-06 ~8 meses; 2022-11/2026-01 ~3.1 anos, sigue abierto
  al final del backtest) los que explican casi todo. Riesgo de margen: PROBLEMA SERIO,
  medido directamente — el peor movimiento de precio EN CONTRA de la pata corta durante
  esos dos holds fue **+407.8%** y **+692.7%** respectivamente. En margen aislado
  (default en la mayoria de exchanges) eso es liquidacion garantizada del short mucho
  antes de completar el hold, pese a que la pata spot ganaba lo mismo simultaneamente —
  el motor de riesgo del exchange no neta ambas patas salvo que la cuenta tenga
  **portfolio margin** habilitado (no es el default, requiere elegibilidad). El backtest
  es ciego a este riesgo por diseño (`adjust_balance` = balance ilimitado). Ademas, las
  ventanas que generan el edge (regimenes alcistas sostenidos) son EXACTAMENTE las que
  mas estresarian la pata corta — edge y riesgo de liquidacion estan correlacionados,
  no son independientes. Cerrado hasta confirmar portfolio margin por escrito en la
  cuenta real; si se reabre, empezar con notional pequeno, no con el 90% de este backtest.
- Razon: pre-registro completo (hipotesis, mecanica, gate) en `docs/income/plan.md` (Via D).
- Permitido en forward-test?: no (nuevo bot aislado, requeriria modelar riesgo de margen
  primero + OK explicito)
- Referencias: `docs/income/plan.md`, `strategies/prop_swing.py` (patron de short sintetico)

### EXP-014 — On-chain exchange-reserve overlay (SplyExNtv, CoinMetrics)
- Fecha: 2026-07-14 (screen, no llego a pre-registro formal — rechazado en la fase mas
  barata, antes de escribir ninguna estrategia/overlay real)
- Estrategia: ninguna (`strategies/onchain_flow.py` — fetch + funciones puras, sin bot)
- Hipotesis: reservas de BTC en exchanges (`SplyExNtv`, CoinMetrics Community API,
  gratis, verificado 2015-hoy) CAYENDO fuerte (ROC 30d en percentil bajo trailing) =
  holders retirando a cold storage = señal bullish; SUBIENDO fuerte = distribucion =
  bearish. Pensado como overlay tipo `swing_funding_overlay.py` (tilt pequeño sobre
  Swing), NO como estrategia direccional standalone — para evitar el patron de fallo
  de EXP-011/012 (otra apuesta direccional correlacionada con Swing).
- Screen (metodologia `alpha_screens.py::consistency`, 2015-2026, umbral trailing 180d
  shift(1) anti-lookahead, p10/p90):
  - Base incondicional fwd7d: +149.1 bps.
  - Reserva CAYENDO (p10, hipotesis bullish): fwd7d +173.5 bps (8/11 anios), fwd30d
    +532.6 bps (7/11).
  - Reserva SUBIENDO (p90, hipotesis bearish): fwd7d +258.8 bps (8/11 anios), fwd30d
    +896.8 bps (7/11) — **MAYOR que el grupo "bullish"**, lo contrario de la hipotesis.
- Decision: **rejected en fase de screen** (mas barato que llegar a implementar overlay
  o tocar swing_allocator.py). Ambos extremos muestran retorno forward positivo, pero
  eso es la deriva alcista de fondo del dataset (BTC 2015-2026 sube fuerte en casi toda
  la muestra) — la asimetria hipotetizada (caida=bullish > subida=bearish) NO aparece;
  si acaso esta invertida. No se llego a pre-registrar formalmente ni a tocar
  `swing_allocator.py` (regla del proyecto: no tocar el frozen sin aprobacion explicita).
- Razon: el screen es la validacion mas barata posible (sin backtest completo, sin
  tocar codigo de estrategia) — fallar aqui evita gastar presupuesto de iteracion en
  algo que ya muestra que la premisa no se sostiene.
- Permitido en forward-test?: no
- Referencias: `strategies/onchain_flow.py`, `tests/test_onchain_flow.py` (funciones
  puras validas, conservadas por si se replantea la hipotesis — p.ej. como filtro de
  riesgo/dispersion en vez de señal direccional, o condicionado por regimen de mercado).
  Continua en EXP-015 (la mitad "riesgo" de la hipotesis, no la direccional).

### EXP-015 — Overlay de riesgo por spike de reserva/stablecoin (vol precursora)
- Fecha: 2026-07-14 (screen extendido de EXP-014 + implementacion + backtest real)
- Estrategia: swing (v6) — `use_flow_vol_overlay` en `SwingAllocatorConfig`
- Hipotesis: aunque la mitad DIRECCIONAL de EXP-014 fallo, el screen extendido (4
  ventanas ROC: 10/30/60/90d, reserva Y stablecoin) mostro un patron consistente y
  robusto que la version original no probo: un spike en percentil alto (p90) de
  reserva/stablecoin precede volatilidad realizada 14d ELEVADA, con 11/11 anios de
  consistencia en las 5 combinaciones probadas (a diferencia de la senal direccional,
  que se invertia segun la ventana). Hipotesis: usar esto como CAP de riesgo (reducir
  target BTC durante el spike, sin importar direccion) podria reducir el Max DD de
  Swing sin sacrificar mucho CAGR — el "frente cerrado" de sesion 15 nunca probo este
  lever especifico (todos los levers previos eran indicadores de PRECIO, este es
  on-chain puro).
- Implementacion: `strategies/onchain_flow.py::load_flow_context/flow_vol_adjustment_at`
  (patron identico a `swing_funding_overlay.py`) + wiring en `swing_allocator.py`
  (`use_flow_vol_overlay=False` default — NO cambia v6-2). Config UNICA pre-comprometida
  (sin grid): ROC 60d, p90, delta -0.15, TTL 14d (= ventana medida de vol forward),
  dedup 14d. `cli/runner.py` carga el contexto igual que macro/market/funding.
- Metricas (2015-2026 realistic, config unica, un solo run — no fitting):

  | | Balance final | CAGR | Max DD | Trades | btc_vs_bnh |
  |---|---:|---:|---:|---:|---:|
  | v6-2 sin overlay (control) | $9.53M | +86.6% | -52.73% | 70 | 0.8499 |
  | v6-2 CON overlay | $6.32M | +79.7% | **-50.79%** | 91 | **0.5638** |

- Decision: **rejected**. Max DD mejora solo 1.94pp (-52.73% -> -50.79%) a cambio de
  -6.9pp de CAGR, +21 trades de churn, y el btc_vs_bnh se desploma de 0.85 a 0.56 —
  el overlay tambien recorta exposicion durante continuaciones alcistas genuinas
  (los spikes de reserva/stablecoin no distinguen "antes de un crash" de "antes de un
  rally", solo anticipan volatilidad, no direccion). Confirma con un lever
  estructuralmente NUEVO (on-chain, no precio) la misma conclusion de sesion 15: el
  Max DD de Swing es un suelo estructural de estar long-only, no arreglable con un
  cap tactico mas. `use_flow_vol_overlay` queda en el codigo (default False, igual que
  `use_mvrv`/`use_rsi`/etc.) por si se reformula, no se borra.
- Razon: un solo backtest limpio (config pre-comprometida desde el screen, sin ajustar
  tras ver el resultado) — coherente con el protocolo anti-overfitting del proyecto.
- Permitido en forward-test?: no
- Referencias: `strategies/onchain_flow.py`, `strategies/swing_allocator.py`,
  `SESSION.md` "Frontera de Max DD... CERRADA" (ahora con un lever on-chain mas en la lista).

### EXP-015 — Short de calendario durante bear_onset (idea, rechazada sin screen)
- Fecha: 2026-07-14 (rechazado en fase de idea — ni screen ni backtest; esta entrada
  existe para que la proxima vez que los graficos "muestren" el patron, la respuesta
  ya este escrita)
- Estrategia: ninguna (propuesta: short BTC ~1 año cubriendo la ventana bear_onset,
  aprovechando que el allocator ya esta en el floor 20% BTC / ~80% USDT)
- Hipotesis: bear_onset ocurre "siempre en la misma ventana y de la misma forma" cada
  4 años → en vez de tener el USDT parado, un unico short de calendario capturaria la
  caida completa.
- Decision: **rejected en fase de idea** (la mas barata posible)
- Razon (cuatro, cada una suficiente por si sola):
  1. **Circularidad**: el patron observado en los graficos es la propia regla del
     allocator reflejada (`delta_bear_onset=-0.30` + floor `min_btc_pct=0.20`,
     anclados al reloj de halving). La unica afirmacion de mercado real debajo es
     "el precio cae en esa ventana" — y eso es **n=3** (2018, 2022, y el ciclo actual
     que aun no ha resuelto). "Exactamente igual cada 4 años" describe 3 puntos.
  2. **Funding**: hasta el fix de `load_funding()` (2026-07-14, ver EXP-013) TODO
     backtest con shorts devengaba funding=0 en silencio. Al modelarlo bien, el unico
     candidato vivo que shorteaba en bear (EXP-010) colapso de 74.8%→45.4% pass y fue
     retirado el mismo dia. Cualquier intuicion previa de "los shorts funcionan en
     bear_onset" se formo sobre numeros sin funding.
  3. **Riesgo de liquidacion, medido**: EXP-013 midio el peor movimiento adverso
     contra una pata corta en holds largos: **+407.8% y +692.7%** — y eso CON hedge
     spot al otro lado. Un short desnudo de ~1 año, si el ciclo que rompe el patron
     es este, no hace drawdown: muere. Asimetria: si acierta gana ~profundidad de la
     caida x notional; si falla 1 vez en 3-4 ciclos pierde el notional.
  4. **El USDT no esta "parado"**: es la polvora seca que financia la recompra de
     accumulation (fuente grande del CAGR del allocator). Usarlo como margen del short
     significa que un margin call fuerza a cerrar el short en perdida o perderse la
     recompra — justo en el peor momento.
  Ademas: shorts/perps dentro de Swing ya estaban "fuera de tesis" (lista no-testear,
  arriba) y la propuesta equivale a "shortear BTC HOY y aguantar hasta ~octubre"
  (estamos en bear_onset ahora mismo) — una decision live sobre el ciclo abierto.
- Derivada VIVA (lo unico que sobrevive de la idea): el coste de oportunidad del
  ~80% USDT ocioso durante bear_onset/accumulation es real. Monetizacion correcta =
  yield de bajo riesgo sobre el stable balance (via income, `docs/income/plan.md`),
  con restriccion dura de liquidez (disponible al instante para la recompra — nada
  con lockup) y counterparty risk evaluado. NO direccional, NO toca v6-2.
- Permitido en forward-test?: no
- Referencias: EXP-013 (riesgo margen medido), EXP-010 (colapso al modelar funding),
  `docs/income/plan.md` (derivada de yield), SESSION.md descartados (shorts/perps)

### EXP-010 — Prop: router CFT-only (entry_halving_phases=bear_onset,accumulation)
- Fecha: ver `docs/prop/hyrotrader-plan.md`
- Estrategia: prop_swing
- Hipotesis: restringir entradas a fases bear_onset+accumulation es el mejor candidato prop encontrado hasta ahora.
- Decision: parked (bloqueado en prerequisito externo)
- Razon: requiere validar reglas reales CFT/Match/MT5 con confirmacion ESCRITA antes de cualquier compra. Sin eso, NO comprar.
- Permitido en forward-test?: n/a (no es una decision de codigo)
- Referencias: `docs/prop/hyrotrader-plan.md`
- **CORRECCION 2026-07-14:** los numeros que promovieron este candidato (2020-26
  74.8% pass / 2.0% breach) se calcularon con `model_funding=True` que era un no-op
  silencioso (bug en `load_funding()`, ver EXP-013). Re-corridos con el fix: **pass
  0.454, breach 0.148** — YA NO cumple el gate de adopcion (>=60% pass). El candidato
  esta corriendo en paper en la VM (`prop_swing_btc_usdt`) sobre numeros invalidos.
  No se ha comprado challenge (sin riesgo de capital real), pero el track record de
  paper acumulado desde el despliegue puede estar tambien afectado si el bot mantuvo
  algun short con funding no devengado — pendiente de verificar en la VM.
