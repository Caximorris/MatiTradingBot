# HYROTRADER_PLAN.md — Estrategia prop firm (HyroTrader/Bybit)

**Creado: 2026-07-03. Estado: P0 RESUELTO (investigacion web oficial 2026-07-03, ver seccion 9).
Plan recomendado: Two-Step $10k-$25k + Swing Drawdown Upgrade. NO implementar aun — falta P1.**

Este documento captura el analisis critico, el diseno condicional de la estrategia y el risk
manager para operar un challenge de HyroTrader con bot por API en Bybit. El plan de
implementacion paso a paso (estilo PLAN_MEJORA_AUDITORIA.md) se creara SOLO despues de cerrar
el checklist P0 — sus respuestas pueden invalidar partes del diseno.

**Veredicto de la sesion de analisis: NO IMPLEMENTAR TODAVIA. Investigar mas (P0 + P1).**

---

## 0. REGLAS DE HYROTRADER (segun brief de Matias, 2026-07-03 — verificar en P0)

1. Bots por API permitidos; HFT prohibido. Estrategia swing / baja-media frecuencia. Evitar
   rafagas de ordenes, cancelaciones constantes, scalping hiperactivo.
2. Prohibido copy trading, mirroring, senales de terceros. Datos externos solo si son datos de
   mercado objetivos (calendarios macro publicos OK; senales copiadas NO).
3. Prohibido arbitraje de latencia, explotacion de feeds externos, errores de precio. Nada
   basado en diferencias Binance/OKX/Bybit vs HyroTrader. Estrategia replicable en mercado real.
4. Daily drawdown TRAILING INTRADIA desde el pico de equity del dia (equity incluye PnL abierto
   y fees). One-Step 4%, Two-Step 5%. Existe "Swing Daily Drawdown Upgrade" con calculo mas
   compatible con swing (mecanica exacta a confirmar en P0).
5. Max perdida por trade: 3% del balance inicial. Disenar muy por debajo, no en el limite.
6. Profit Distribution Rule: ningun dia > 40% del beneficio neto total de la evaluacion.
7. Funded: max 25% del balance inicial como margen abierto; max notional acumulado 2x balance.
8. Ejecucion API en Bybit. Considerar fallos de API, desconexiones, rechazos, fills parciales,
   latencia. Logs y trazabilidad completa por operacion.
9. Sin fills perfectos: comisiones, spread, slippage, rechazos. Penalizar entradas/salidas
   muy ajustadas.

---

## 1. FASE 1 — Auditoria del Swing v5 vs HyroTrader

**Conclusion dura: el Swing Allocator v5 NO es adaptable a HyroTrader. Descartado como
estrategia para este fin.** Su tesis (100% del tiempo en mercado, 20-100% de exposicion,
tolerar -52% DD para maximizar valor terminal a anos) es la negacion de lo que una prop firm
paga. Lo reutilizable es la infraestructura, no la estrategia.

**Reutilizable [Certain]:**
- Motor de backtest (`core/backtest.py`): equity horaria, costes configurables, determinismo
  por cache, `fill_next_open`.
- Disciplina metodologica: anti-lookahead (`daily_on_closed_only`), walk-forward, ablations,
  ventanas fijas, bootstrap MC (`tools/bootstrap_equity.py`), protocolo anti-overfitting.
- Senal de regimen EMA50D/200D + ADX (dias cerrados) — como FILTRO direccional.
- Infra operativa: registry, journals, telegram remote, parity check, degradation report, tests.

**Letal para HyroTrader [Certain]:**
1. Daily DD trailing: con 60-100% BTC sin stop, un dia de BTC -5% (~2-4% de las sesiones) =
   breach del One-Step. Max DD historico -52.73%, underwater 922d. Esperanza de vida: dias.
2. Sin concepto de trade con stop: la regla de 3%/trade es inaplicable a un rebalanceo sin stop.
3. Market orders del 10-30% del balance por rebalanceo.
4. Profit Distribution incontrolable: PnL = curva continua concentrada en tramos parabolicos
   (Q2 2021: +$1.14M en un trimestre).
5. El edge (fases de halving, ciclos 4 anos) no cabe en el horizonte de un challenge (semanas).

**NO es problema:** frecuencia (~6 rebalanceos/ano, nada parecido a HFT), ni copy/arbitraje
(senales = OHLCV propio + calendario halving).

**Supuestos irreales del backtest actual para prop [Certain]:**
- Es SPOT OKX; HyroTrader = PERPS Bybit. Falta funding (~0.01%/8h tipico, picos 10x) — material
  en holds multi-dia. Falta modelo de margen/liquidacion.
- Fills al close con slippage fijo; sin spread, sin rechazos, sin fills parciales.
- Equity horaria SUBESTIMA picos/valles intradia del trailing DD (que es tick-real).
- `core/risk_manager.py` actual: solo PnL realizado del dia vs balance USDT. Sin equity con
  uPnL, sin fees, sin margen/notional, sin trailing, sin profit distribution. Ademas usa
  `date.today()` local para el corte del dia (el reset de HyroTrader tendra su timezone).
- Metricas actuales (CAGR/MaxDD 11 anos, PF/WR) no responden "P(pasar challenge sin breach)".

---

## 2. FASE 2 — Objetivo de diseno

Metrica principal: **P(pasar challenge sin breach) x P(sobrevivir >=6 meses funded)**.
Prioridades en orden: 1) no romper reglas, 2) sobrevivir daily DD, 3) no concentrar profit,
4) reducir riesgo de ejecucion irreal, 5) rentabilidad razonable, 6) sin sobreoptimizacion,
7) misma logica en funded. NO optimizar por CAGR/PF.

Esto implica una estrategia NUEVA de trades discretos que hereda del Swing el filtro de
regimen y la infraestructura. No es "adaptar el Swing" — es otro producto.

---

## 3. FASE 3 — Diseno: "Prop Swing" (trend-pullback discreto) [Likely — pendiente validacion]

- **Timeframes:** regimen y filtros en 1D cerrado; setup y ejecucion en 4H cerrado. Nada <1H.
  Frecuencia estructural: 2-6 trades/semana.
- **Opera:** solo long con regimen bull (EMA50D>EMA200D + precio>EMA200D + ADX>umbral).
  Short solo si backtest separado lo justifica — empezar long-only.
- **Bloqueos:** regimen bear/lateral (ADX bajo); ATR% diario en percentil extremo (vol tipo
  COVID); ventana +-30-60min alrededor de eventos macro programados (FOMC/CPI — calendario
  publico objetivo); spread observado > umbral al ordenar; fin de semana a evaluar (no asumir).
- **Entrada:** pullback a zona EMA20D / EMA50-4H en tendencia + gatillo de reanudacion (cierre
  4H sobre el high de la vela previa). Orden LIMIT post-only; si no llena en N velas, cancelar.
  Nunca perseguir precio con markets grandes.
- **Stop:** SIEMPRE, en el exchange (orden condicional real), 1.5-2.0x ATR(4H) bajo entrada.
  El stop dimensiona la posicion, no al reves.
- **Gestion:** TP1 50% en +1R; stop a break-even tras TP1; resto trailing por estructura 4H
  (swing lows) o chandelier ATR. Sirve a 3 reglas a la vez: no devolver beneficio intradia,
  suavizar distribucion diaria de PnL, cortar colas.
- **Riesgo por trade: 0.5% del balance inicial.** 0.25% no llega al target en tiempo razonable
  con 2-6 trades/semana; 1% deja poco margen ante gap nocturno 3x stop. Worst-case con
  gap/slippage 3x ~= -1.5% = mitad del limite oficial de 3%. Subir a 0.75% solo con evidencia
  del simulador.
- **Limites internos:** 1 posicion simultanea (solo BTC); max 2 entradas/dia; dia a -1.5% ->
  no mas entradas; -2.5% desde pico del dia -> flatten total (kill switch); dia a +2.5% ->
  no abrir mas y apretar stops (un dia muy verde sube el pico trailing Y concentra profit).
- **Profit Distribution:** ledger diario; si el dia en curso supera ~30% del profit neto
  acumulado -> modo distribucion (cerrar parcial, apretar stop, no abrir mas ese dia). NUNCA
  forzar trades para diluir — se diluye con tiempo, no con operaciones malas.
- **Funded por construccion:** 0.5% riesgo + stop ~3-4% del precio => notional ~12-17% del
  balance. Muy por debajo de 2x notional y 25% margen. Misma config challenge y funded.
- Sin grid, sin martingala, sin promediar en contra.

---

## 4. FASE 4 — HyroRiskManager (modulo nuevo, NO parchear el actual)

Capa nueva especifica prop (el `RiskManager` actual queda para OKX). Persistencia en disco
(patron `paper_state.json`). Debe trackear: initial_balance, equity (balance + uPnL mark +
fees devengadas), day_peak_equity (trailing, reset en timezone HyroTrader — confirmar), PnL
cerrado del dia, fees del dia, riesgo vivo por posicion (distancia a stop x tamano), margen
usado, notional abierto, trades dia/semana, ledger diario para Profit Distribution, y
**distancia al breach** = equity - day_peak_equity x (1 - dd_oficial) como metrica de primera
clase (logueada cada tick, expuesta en /status de Telegram).

**Valores propuestos [Likely — el simulador los ajustara]:**

| Limite | Interno | Oficial |
|---|---|---|
| Riesgo por trade | 0.5% (worst-case gap <=1.5%) | 3% |
| Perdida diaria — bloqueo entradas | -1.5% desde pico del dia | 4%/5% |
| Perdida diaria — flatten total | -2.5% desde pico del dia | 4%/5% |
| Distancia al breach — bloqueo entradas | <1.5% equity | — |
| Distancia al breach — cerrar todo | <0.75% equity | — |
| DD total interno | -5% -> pausa y revision manual | (confirmar oficial) |
| Profit diario — freno operativo | +2.5% | — |
| Dia como % del profit total | >30% -> modo distribucion | 40% |
| Trades/dia | 2 | — |
| Trades/semana | 8 | — |
| Margen usado | <=15% | 25% |
| Notional abierto | <=1.0x balance | 2x |

Estado de emergencia: incoherencia estado local vs exchange (posicion huerfana, orden
desconocida, stop ausente) -> flatten + bloqueo + alerta Telegram. Un bot sin stop en el
exchange durante una desconexion es el escenario de ruina #1.

---

## 5. FASE 5 — Backtest adaptado

Modulo nuevo de simulacion de reglas prop POR ENCIMA del motor, no entremezclado:

1. **Modelo Bybit perp:** fees maker/taker reales, funding cada 8h (reusar `funding_context`),
   spread fijo + slippage estocastico, prob. de rechazo/no-fill en limits, fills parciales.
2. **Equity intradia:** usar high/low de velas 1H para acotar pico/valle intrabar. Aun asi
   subestima el tick real -> evaluar breach con buffer (~20% del limite).
3. **Simulador de challenge:** ventanas rodantes (inicio cada semana, 2018->2026); cada ventana
   termina en PASA / BREACH (daily o total) / PROFIT-RULE / TIMEOUT. Metricas que mandan:
   **P(pasar), P(breach), P(fallo por concentracion), dias medios hasta pasar, % de dias con
   distancia al breach <1%**.
4. **Monte Carlo trade-level:** permutacion/bootstrap de la secuencia de trades (el trailing DD
   es path-dependent; el bootstrap mensual existente NO basta).
5. **Sensibilidad obligatoria:** slippage x2 y x3, fees +50%, spread x2, funding percentil
   alto. Si P(pasar) se derrumba con slippage x2, la estrategia no existe.
6. **Baseline de verguenza:** correr el Swing v5 por el mismo simulador y documentar su
   P(breach) (~100% [Likely]). Contraste + prueba de que el simulador muerde.
7. Metricas legacy (CAGR, PF, Sharpe/Sortino, rachas, duracion media) = secundarias.

---

## 6. FASE 6 — Plan por fases (esqueleto; el PLAN_* detallado se escribe tras P0)

- **P0 — BLOQUEANTE (Matias, con HyroTrader):** ver checklist abajo.
- **P1 — `core/prop_rules.py`:** simulador de reglas prop. **HECHO 2026-07-03.**
  Modulo estrategia-agnostico: consume `equity_curve` de cualquier BacktestResult y evalua
  daily DD (trailing/swing-estatico, reset UTC, importe fijo % del inicial), max loss total,
  3% realizado por trade, target + dias minimos, Profit Distribution 40% (no-terminal: espera
  dilucion), `intrabar_buffer` (default recomendado 0.2 — equity 1H subestima picos tick).
  Presets ONE_STEP / TWO_STEP_P1 / TWO_STEP_P2; two-step encadenado con rebase.
  Runner: `tools/prop_challenge_sim.py --strategy X --from --to --buffer 0.2` (ventanas
  rodantes cada 7d, 4 configs). Tests: `tests/test_prop_rules.py` 17/17 (suite 118/118).
  **Baseline de verguenza EJECUTADO** (Swing v5, 2018-2026 realistic, buffer 0.2, ~410
  ventanas): pass_rate 0.000 y breach_rate 1.000 EN LAS 4 CONFIGS (one/two-step, con y sin
  Swing Upgrade). Peor DD diario observado 9.86% vs limites 4-5%. Desglose two_step_swing:
  314 breach_daily / 88 breach_total / 6 trade_loss. Confirma FASE 1 con numeros: el
  allocator es inviable en prop; el simulador muerde. Pendiente P4: correr el candidato
  Prop Swing (P3) por este mismo simulador — criterio go/no-go: P(pasar)>=60% con buffer 0.2.
- **P2 — `core/hyro_risk.py`:** HyroRiskManager + tests exhaustivos. Este modulo es el
  producto; la estrategia es secundaria.
- **P3 — `strategies/prop_swing.py`** + entrada en `strategies/registry.py`, reusando
  `strategies/indicators.py` y el regimen. Config default = tabla de FASE 4.
  **HECHO 2026-07-03 (v0).** Implementado segun FASE 3: regimen 1D cerrado (EMA50/200+ADX),
  entrada pullback EMA50-4H + gatillo de reanudacion en cierre 4H, stop 2xATR4H siempre,
  TP1 50% en +1R + break-even + chandelier 3xATR, risk 0.5%, cap notional 25%, limites
  diarios internos (-1.5% no entradas / -2.5% flatten / +2.5% no entradas), max 2/dia.
  Alias CLI: `--strategy prop_swing` o `prop`. Suite 118/118.
  **Resultado v0 por el simulador (2018-2026 realistic, buffer 0.2, 366 ventanas):**
  - SUPERVIVENCIA RESUELTA: breach_rate ~0.000 (1 breach_total en 1464 challenges),
    worst daily DD 1.03% vs limite 4-5%, near_breach 0%. Los limites internos funcionan.
  - SIN MOTOR: pass_rate 0.000 — TIMEOUT ~100%. Nunca alcanza el 10% en 365 dias.
    Smoke 2022-2024: 0 trades en el bear 2022 (regimen OK), pero expectancy negativa en el
    chop 2023 (avg win +30 vs avg loss -44): TP1@1R+BE produce ganadores de ~0.5R contra
    perdedores de 1R — necesita WR>67% y da 50%. DEFECTO ESTRUCTURAL del esquema de salidas,
    no fitting de ventana. Ademas 10% target con 0.5% risk = 20R netos: infraalimentado.
  **Diagnostico P4:** el problema es el motor (expectancy y potencia), no el riesgo. Hay
  5x de margen sin usar contra los limites (worst daily 1% vs 4-5%). Candidatos a iterar
  AISLADOS en P4: (a) risk 0.75-1.0% (10% = 10-13R netos; worst daily estimado ~2%),
  (b) salidas: quitar BE inmediato post-TP1 o TP1 a 1.5R (matar el sesgo 0.5R/1R),
  (c) trailing sobre high en vez de close. Protocolo: un cambio por vez, 2018-2026 completa,
  metrica = P(pasar)/P(breach) del simulador con buffer 0.2, NO CAGR.

- **P4 — EXPERIMENTOS AISLADOS (2026-07-03, 2018-2026 realistic, buffer 0.2, un cambio/run):**
  | Exp | Cambio | 1-step pass | 1-step breach | Edge (PF/expectancy) | Veredicto |
  |---|---|---|---|---|---|
  | v0 | — | 0.000 | 0.003 | 1.11 / +$2.07 (+4.8% en 8a) | sin motor |
  | E1 | risk 1% | 0.131 | 0.185 (todo breach_total 6%) | = v0 | amplifica, no crea |
  | E2 | tp1_r 1.5 | 0.000 | 0.016 | — | PEOR, descartado |
  | E3 | be_after_tp1=False | 0.000 | 0.022 | — | PEOR, descartado |
  | E4 | trail_on_high | 0.000 | 0.003 | — | INERTE, descartado |
  | E5 | entry_mode=breakout (Donchian 20x4H) | 0.000 | 0.003 | 1.26 / +$4.69 (+9.6%, DD -5.24%) | MEJOR motor aislado |
  Journal v0: 76 stop_loss (-1R) vs 76 stop_be (WR 98.7% pero ~0.5R) — el chandelier casi
  nunca captura runner; la entrada pullback-reclaim no tiene alfa a este horizonte. E2/E3
  (aflojar salidas) solo anaden colas. Flags nuevos en config: entry_mode ("pullback"|
  "breakout"), breakout_lookback_4h=20, be_after_tp1, trail_on_high (defaults = v0).
  **E6 = E5+risk1%** (mejor candidato final): edge +14.98% en 8a / PF 1.27 / DD -6.61%.
  One-Step: pass 11.8% / breach 2.7% / timeout 85.6% / mediana 210 dias para pasar.
  Two-Step: 0% (15% acumulado inalcanzable con este motor). **E6b (0.75%): 0% pass** —
  por debajo de 1% de riesgo ni siquiera las mejores ventanas llegan al target en 365d.

  **CHECKPOINT FASE 7 DISPARADO (2026-07-03): senal de abandono cumplida.**
  P(pasar) maximo alcanzado = 11.8% << 40% (umbral de abandono) << 60% (go/no-go).
  El motor es real pero pequeno (PF ~1.26 con costes realistic, ~1.9%/ano a 1% risk) y la
  aritmetica del challenge (10% en meses) exige un riesgo/trade que nuestro diseno prohibe.
  EV negativo: coste esperado en fees para conseguir 1 cuenta funded $10k ~ $208 x 0.88/0.118
  ~ $1.6k; la cuenta funded generaria ~$150/ano al 80% con este motor. NO comprar challenge.
  Palancas NO exploradas (con prior esceptico, requieren OK explicito): allow_shorts en bear
  (otro ciclo de diseno), alfa intradia genuina (riesgo alto de overfit-hunting), otros
  activos. Recomendacion: NO IMPLEMENTAR MAS / no comprar challenge con este motor;
  la infraestructura (prop_rules, prop_swing, flags) queda lista si aparece un motor mejor.
- **P4 — Validacion:** simulador challenge ventanas rodantes + MC trade-level + WF +
  sensibilidad costes + baseline Swing v5. Reglas invariantes del proyecto aplican (cambios
  aislados, ventanas fijas, sin fitting a eventos unicos, finales en conservative).
- **P5 — Ejecucion:** `core/exchange_bybit.py` espejo de `OKXClient` (el patron
  BacktestClient=OKXClient ya probo la abstraccion); semanas de Bybit testnet antes de
  challenge real; logs por trade con trazabilidad completa.

**Decisiones que requieren OK de Matias antes de programar:** todo P0; long-only vs
long/short; comprar o no el Swing Upgrade; risk/trade final; challenge con bot desde dia 1 o
tras N semanas de testnet.

### Checklist P0 — RESUELTO 2026-07-03 (ver seccion 9 para detalle y fuentes)

- [x] Max drawdown TOTAL: One-Step 6% / Two-Step 10% del balance inicial.
- [x] Targets: One-Step 10% (min 5 dias trading); Two-Step 10% + 5% (min ~10+5 dias, dato
      third-party). Tiempo ILIMITADO en ambos.
- [x] Profit Distribution: "ningun DIA de trading > 40% del resultado neto total" — SOLO en
      evaluacion, NO aplica en funded. Con target 10%, ningun dia puede superar ~4% de equity;
      nuestro freno interno de +2.5%/dia lo cumple con margen.
- [x] Swing Daily Drawdown Upgrade: +$89, SOLO al comprar el challenge (no upgradeable despues).
      Convierte el daily DD de trailing-desde-pico-intradia a ESTATICO desde el equity de
      inicio del dia. Los beneficios intradia NO suben el suelo. Recalcula cada dia.
- [x] Reset diario: medianoche UTC. Equity incluye uPnL y fees.
- [x] Plataforma: Bybit via API (o CLEO). Leverage hasta 100x (no lo necesitamos: notional
      objetivo ~12-17%). Overnight y fin de semana PERMITIDOS sin condiciones.
- [x] EV sketch: challenge $10k Two-Step+Swing ~$208 / $25k ~$338. Fee REEMBOLSABLE al pasar.
      Split 80-90%, payout minimo $100, 12-24h en USDT/USDC. Con ~3%/mes en funded $25k =
      ~$600/mes al 80%. EV positivo si P(pasar) >~40% y supervivencia >2 meses.

Quedan abiertos (no bloqueantes para P1, si para comprar el challenge):
- [ ] Confirmar con soporte los dias minimos oficiales del Two-Step (el 10+5 es third-party).
- [ ] Confirmar si un dia debe tener trades con "notional >=5% del balance y ±1% PnL" para
      contar como dia de trading (dato third-party — afecta al ritmo del bot).
- [ ] Confirmar si el Swing Upgrade cambia tambien la mecanica del max loss total.
- [ ] Confirmar politica de bots en evaluacion por escrito (el marketing dice HFT/arbitraje
      friendly — contradice el brief inicial; para nuestra frecuencia es irrelevante, pero
      mejor tener el OK por escrito antes de conectar el bot).

---

## 7. FASE 7 — Preguntas dificiles (respuestas de la sesion de analisis)

- **Swing + trailing daily DD tiene sentido?** Solo con notional pequeno (10-20%). El conflicto
  real es el gap nocturno contra un limite intradia. Con 0.5% de riesgo y stop en exchange,
  sobrevive. El allocator, jamas.
- **Swing Upgrade o adaptar?** [Guessing hasta P0] Si convierte el daily DD en balance-based/
  EOD, probablemente SI compensa para holds multi-dia. Pero disenar para sobrevivir SIN el
  upgrade; tratarlo como margen extra, no requisito.
- **Profit Distribution mata la baja frecuencia?** Es el riesgo regulatorio #1, por delante del
  drawdown. Si es estricta, empuja a mas trades pequenos (6-8/semana sigue sin ser HFT).
- **Estamos forzando una estrategia real en reglas artificiales?** Si, asumido: la prop firm
  paga gestion de riesgo de corto plazo, no tesis de ciclo. El Swing v5 sigue siendo mejor
  vehiculo para capital propio en OKX; esto es una linea de negocio separada.
- **Tipo mas adecuado:** trend-pullback 4H (propuesto) o breakout con compresion de vol.
  Mean reversion pura = la peor bajo trailing DD (colas y rachas).
- **Cuando NO merece la pena HyroTrader:** profit distribution sin minimo de dias; trailing
  tick-based sin upgrade razonable; EV negativo (cuenta del checklist P0).
- **Que debe demostrar el backtest:** P(pasar) >=60% por intento con costes conservadores,
  P(breach) <=20%, robustez a slippage x2, ningun subperiodo concentra el resultado.
- **Senales de abandono:** P(pasar) <40%; edge desaparece con costes conservadores; o la
  aritmetica target/tiempo/DD exige un risk/trade con P(breach) explosiva. Si el trio es
  incompatible, no hay parametro que lo arregle.

---

## 8. CONCLUSION Y PROXIMO PASO

**NO implementar todavia.** Dos pasos baratos y en orden:
1. **P0** (Matias): respuestas de HyroTrader + cuenta de EV. Una respuesta mala mata el
   proyecto gratis, antes de escribir codigo.
2. **P1** (`core/prop_rules.py`): simulador de reglas prop. Convierte "pasaria un challenge?"
   en un numero y permite correr prototipo y baseline por las mismas reglas.

La decision de implementar la estrategia completa se toma cuando el simulador de P1 de
P(pasar) sobre el prototipo — no antes. Tras P0, crear `PLAN_HYROTRADER.md` con el paso a
paso estilo F1-F19.

Confianza: diagnostico del Swing actual [Certain]; direccion del diseno [Likely]; numeros
finos [Guessing] hasta que el simulador hable.

---

## 9. P0 — REGLAS VERIFICADAS DE HYROTRADER (investigacion web, 2026-07-03)

Fuentes: hyrotrader.com (home, /crypto-trading-rules/, FAQs oficiales de /faq/rules/) +
proptradingvibes.com como third-party para huecos. Donde chocan, manda la FAQ oficial.

### Planes y precios

| | One-Step | Two-Step |
|---|---|---|
| Profit target | 10% | 10% (F1) + 5% (F2) |
| Daily drawdown | 4% | 5% |
| Max loss total | 6% del balance inicial | 10% del balance inicial |
| Dias minimos | 5 | ~10 + 5 (third-party, confirmar) |
| Tiempo limite | ilimitado | ilimitado |

Precios challenge: $5k=$59, $10k=$119, $25k=$249, $50k=$379, $100k=$579, $200k=$969.
Fee reembolsable al pasar. Split 80% -> 90% (+5% cada 4 meses). Payout min $100, 12-24h,
USDT/USDC. Inactividad: 90 dias. Cuentas $5k-$200k, escalado hasta $1M.

### Mecanica del daily drawdown (FAQ oficial)

- **Standard (trailing):** `DD = pico de equity del dia - minimo de equity posterior al pico`.
  Incluye uPnL y fees. El limite es un IMPORTE FIJO (X% del balance inicial) anclado a un pico
  movil. Un retroceso intradia desde el pico BREACHEA AUNQUE EL DIA SEA POSITIVO.
- **Swing (fixed), upgrade +$89 SOLO al comprar:** suelo estatico = equity de inicio del dia
  - X% del balance inicial. Los beneficios intradia no suben el suelo. Recalcula cada dia.
- Reset: medianoche UTC. Chequeo continuo, no solo EOD.

### Reglas verificadas en FAQ oficial

- **Max loss por trade: 3% del balance inicial, perdida REALIZADA** (no flotante). OJO: "no
  monitorizado por el sistema automatico, revision MANUAL" — riesgo de interpretacion; nuestro
  0.5% de riesgo lo deja lejos.
- **Stop loss NO obligatorio** (FAQ oficial; una review third-party decia "obligatorio en 5
  min" — desactualizada). Nosotros lo ponemos SIEMPRE igualmente.
- **Profit Distribution 40%: por DIA, solo evaluacion, no funded.**
- **Funded only: max 25% del balance inicial como margen total; max notional 2x.** NO aplican
  en evaluacion (pero disenamos para cumplirlas desde el dia 1).
- **Overnight y weekend holding PERMITIDOS** sin condiciones.
- Prohibido: Martingale, hedging entre cuentas, low-caps (<$100M) >5% del balance, pares
  EUR/USD y USDC, mezclar spot y margen en la misma cuenta, operar "solo por noticias".
- Ejecucion: Bybit via API (o plataforma propia CLEO). Leverage hasta 100x segun par.
- Politica de bots: API automation soportada (el marketing presume incluso de HFT-friendly,
  lo que contradice el brief inicial — irrelevante para nuestra frecuencia, pero pedir OK por
  escrito antes de conectar).

### Recomendacion de plan (2026-07-03)

**Two-Step $10k (primer intento de validacion) o $25k + Swing Drawdown Upgrade (+$89).**

Razonamiento:
1. **Two-Step sobre One-Step:** el max loss es el techo de supervivencia del bot. 10% vs 6%
   casi duplica el margen ante rachas; daily 5% vs 4% idem. El precio es targets acumulados
   15% vs 10% y mas dias minimos — pero el tiempo es ilimitado y un bot no se cansa. Para
   maximizar P(pasar sin breach), Two-Step gana claramente. One-Step solo si se prioriza
   velocidad sobre probabilidad.
2. **Swing Upgrade SI:** nuestro diseno (TP parcial + trailing en 4H) produce retrocesos
   estructurales desde picos intradia — exactamente lo que el trailing standard castiga
   (breachea aunque el dia sea verde). El upgrade elimina ese modo de fallo por $89.
   Ademas habilita holds multi-dia sin miedo al pico intradia.
3. **Tamano:** $10k ($119+$89=$208) como primera bala de validacion en real; escalar a
   $25k-$50k cuando el simulador de P1 y un challenge pasado lo justifiquen. Las reglas son
   porcentuales — el bot no distingue tamanos.

### Consecuencia para el diseno de FASE 3 (intradia vs swing corto)

Matias planteo pasar a intradia puro. Con el Swing Upgrade el overnight es seguro (suelo
estatico + weekend holding permitido), asi que NO hace falta forzar cierre same-day, que
recortaria expectancy por trade y subiria fees/trade count. Diseno recomendado: **swing corto
(holds de 4h a 3 dias) en 4H con el upgrade**, con time-stop opcional. La variante intradia
pura (cierre antes de medianoche UTC) queda como candidato B para el simulador de P1 — es
una decision EMPIRICA, no de opinion: el simulador debe correr ambas.

Con target F1 = 10% y regla del 40%: ningun dia puede aportar >4% de equity al pasar justo.
Nuestro freno interno de +2.5%/dia ya lo cumple con margen. El limite interno de perdida
diaria (-1.5%/-2.5%) tambien es coherente con el 5% oficial del Two-Step.

---

## 10. H1 — RE-MEDICION POST-CHECKPOINT (2026-07-03, sesion 17)

Tras el checkpoint de abandono, se midieron las palancas GRATIS (sin tocar la estrategia)
que podian estar sesgando el 11.8% al pesimismo: (a) timeout 365d artificial (el challenge
real es ilimitado), (b) arranques aleatorios vs arranque condicionado a regimen bull,
(c) matriz salidas x breakout (E2/E3/E4 solo se habian medido sobre el motor pullback v0).
Tooling: `--max-days` (lista) y `--bull-start` en `prop_challenge_sim.py`; `start_filter`
y herencia de `max_days` en fase 2 en `core/prop_rules.py`. Tests 17/17. El run baseline
@365d reproduce el 11.8% de P4 (validacion del tooling).

Resultados (2018-2026 realistic, buffer 0.2, one_step_std / two_step_std):

| Variante | Edge 8a / PF / maxDD | 1-step @365 | 1-step @540 | 1-step @730 | 2-step @540 |
|---|---|---|---|---|---|
| E6 baseline | +15.0% / 1.27 / -6.6% | 0.118 | 0.193 | 0.210 | 0.000 |
| E6 + tp1_r 1.5 | +20.3% / 1.33 / -10.1% | 0.103 | **0.243** | — | **0.182** |
| E6 + be_after_tp1=False | +16.2% / 1.29 / -7.2% | 0.117 | 0.192 | — | 0.000 |
| E6 + trail_on_high | +11.6% / 1.20 / -7.2% | 0.000 | 0.000 | — | 0.000 |

Hallazgos:
1. **GATE FALLADO.** Maximo absoluto alcanzable con palancas gratis: 24.3% one-step /
   18.2% two-step (@540d, tp1.5) << 30% (gate H1) << 60% (go/no-go). Mediana para pasar
   el two-step: 830 dias (2.3 anos). El tiempo ilimitado ayuda pero PLATEA (~21% @730d):
   el motor gana ~2%/ano y ni la eternidad convierte eso en 15% acumulado fiable.
2. **bull-start REFUTADO (al reves de la hipotesis):** arrancar en regimen bull EMPEORA
   (1-step @365: 0.5% vs 11.8%; breach sube 2-3x). Los pases provienen de ventanas que
   arrancan en bear, esperan planas y capturan el giro de regimen desde el inicio;
   arrancar en mitad del bull = entrar tarde en el chop del techo. La palanca "comprar el
   challenge cuando ya es bull" esta MUERTA tal cual (refinamiento no medido: condicionar
   al cruce RECIENTE de regimen).
3. **Salidas x breakout:** tp1_r=1.5 SI mejora sobre breakout (PF 1.33, unico two-step
   no-nulo) — el veredicto E2 de P4 era especifico del motor pullback. be_after_tp1
   neutro. trail_on_high letal (mata los pocos runners que pasan). Nuevo mejor candidato:
   **E7 = breakout + risk 1% + tp1_r 1.5**, con mas cola (breach one-step 14% @540d).
4. **EV sigue negativo:** P~0.18-0.24 con mediana 1-2.3 anos por intento. El veredicto
   NO COMPRAR del checkpoint FASE 7 se mantiene.

Consecuencia: las palancas gratis no bastan. Para reabrir el proyecto hace falta un salto
de 3-5x en expectancy x frecuencia. Candidatos estructurales (requieren OK explicito,
ver analisis sesion 17): H2 = shorts en regimen bear (espejo del breakout; duplica
disponibilidad, funding a favor, resuelve inactividad 90d), H3 = multi-simbolo (ETH+)
con cap de riesgo agregado por correlacion, H4 = filtro de compresion de vol sobre el
breakout. Gates si se ejecutan: seguir solo si P(pasar) two-step >= 40%; comprar solo
con >= 60% + robustez slippage x2. Si tras H2+H3 sigue < 40%: ABANDONO DEFINITIVO.

---

## 11. H2/H3 — SHORTS Y MULTI-SIMBOLO (2026-07-03, sesion 17, OK de Matias)

**Implementacion H2** (`strategies/prop_swing.py`, `allow_shorts=False` default — v0/E7
intactos, invarianza verificada con smoke identico pre/post refactor; tests 118/118):
regimen bear = espejo exacto (EMA50D<EMA200D + close<EMA200D + ADX>=adx_min), breakout
Donchian a la baja, stop/TP1/chandelier invertidos. Shorts SINTETICOS solo backtest
(requieren `adjust_balance`): mark-to-market barra a barra contra el balance USDT para
que el trailing DD vea el uPnL en continuo (los shorts de pro_trend NO hacen MTM — su
equity se congela durante el short; inaceptable para reglas prop). Costes identicos a
`_fill_market`; fee de apertura prorrateado en los cierres parciales. `self.realized`
= (ts, pnl neto) de cada cierre (long+short), fuente por-trade del simulador (los
sinteticos no pasan por el pairing ACB). En Bybit real seran perps nativos (P5).

**Implementacion H3** (`tools/prop_challenge_sim.py --symbols A,B`): curva portfolio =
sleeves independientes de $10k por simbolo, equity sumada, trades concatenados. Con n
sleeves a riesgo r, el riesgo por trade a nivel cuenta es ~r/n.

**Resultados (realistic, buffer 0.2, E7 = breakout + risk 1% + tp1_r 1.5):**

| Config | Ventana | Edge / PF / maxDD | 1-step @540d (breach) | 2-step @540d (breach) |
|---|---|---|---|---|
| E7 long-only | 2018-26 | +20.3% / 1.33 / -10.1% | 0.243 (0.141) | 0.182 (0.018) |
| **E8 = E7+shorts** | 2018-26 | +41.1% / 1.30 / -12.5% | **0.485** (0.191) | **0.308** (0.085) |
| E7 long-only | 2020-26 | +10.4% / 1.19 / -10.1% | 0.117 (0.199) | 0.004 (0.026) |
| **E8 = E7+shorts** | 2020-26 | +27.3% / 1.18 / -12.5% | **0.401** (0.263) | **0.348** (0.121) |
| E7 BTC+ETH 1% | 2020-26 | ETH sleeve: +1.3% / 1.03 | 0.209 (0.308) | 0.073 (0.188) |
| E7 BTC+ETH 2% | 2020-26 | ETH sleeve: -2.3% / 0.96 | 0.210 (0.356) | 0.000 (0.263) |
| E8 BTC+ETH 1% | 2020-26 | ETH sleeve: -7.6% | 0.435 (0.438) | 0.200 (0.236) |

**Conclusiones:**
1. **H2 ADOPTADO como candidato (E8).** Los shorts ~2-4x el pass rate en las DOS ventanas
   (robusto, no window-fitting). El bear 2022 pasa de 0 trades a +14.2% con maxDD 3.4%.
   Resuelve ademas la inactividad de 90d. Worst daily DD 2.0% — el daily nunca es el
   modo de fallo; TODOS los breach son max-loss-total.
2. **H3 RECHAZADO (no reintentar).** ETH con este motor no tiene edge en ninguna
   direccion (long PF 1.03; con shorts -7.6% el sleeve). Anade varianza, no alfa:
   sube pass one-step pero sube breach mas (0.438 vs 0.263) y HUNDE el two-step
   (0.200 vs 0.348). El edge del breakout-regimen es BTC-especifico.
3. **Insight estructural: la regla que mata es el MAX LOSS TOTAL (6% one-step / 10%
   two-step), no el daily DD ni el target.** El two-step domina al one-step en
   supervivencia (breach 0.085 vs 0.191 en 2018-26) y a 365d incluso pasa MAS que el
   one-step en 2020-26 (0.222 vs 0.208). Confirma Two-Step como plan correcto.
   Corolario NO testeado: risk >1% podria pagar en two-step (el techo de 10% tiene
   margen) aunque E1 demostro que amplifica breach en one-step (techo 6%).
4. **GATE: dos-step mejor = 0.348 (2020-26) / 0.308 (2018-26) < 40%.** Formalmente en
   zona de abandono. Mediana para pasar two-step ~490 dias (~1.4 anos/intento) — el
   tiempo, no solo la probabilidad, sigue lastrando el EV. Swing Upgrade (+$89) inerte
   en todas las filas (el daily nunca muerde) — NO comprarlo con este motor.

**Estado: E8 congelable; decision de Matias pendiente entre (a) abandono definitivo por
gate <40%, o (b) exactamente DOS runs finales medidos antes del cierre: risk 1.25% y
1.5% sobre E8 two-step (dimension nunca testeada bajo el techo de 10%; E1/E6b eran
one-step-era) y/o H4 squeeze. Sin mas iteraciones despues, pase lo que pase.**
[Decision de Matias 2026-07-03: opcion (b) + H4. Resultado en seccion 12.]

---

## 12. RUNS FINALES Y VEREDICTO DE CIERRE (2026-07-03, sesion 17)

**H4 squeeze: RECHAZADO sin ambiguedad.** `use_squeeze` (ATR%4H bajo su mediana de 90
bloques) mata el edge: +3.7% en 8 anios (vs +41% E8), two-step @540d 7.0%. Filtra
exactamente los breakouts buenos. Flag queda en config (default False), no reintentar.

**risk 1.25%/1.5% sobre E8: runs NULOS — descubrieron el artefacto del cap.** Subir el
riesgo no cambio nada (mismos 184 trades, mismo PnL) porque `max_notional_pct=0.25`
clampeaba el sizing: con stop 2xATR4H (~1-3% del precio), risk>=1% implica notional
33-100% y el cap de 25% lo recorta. **El riesgo efectivo de TODO el proyecto habia sido
~0.25-0.75%, nunca el configurado.** El cap 25% era proxy de spot sin apalancamiento;
en Bybit perps el limite funded real es margen<=25% y notional<=2x: con 4-5x de
leverage, notional 50% = margen 10-12% (legal). Se midio el des-clampeo como cambio
estructural aislado (E9 = E8 + `max_notional_pct=0.5`):

**Matriz de decision E9 (two-step @540d, pass/breach; one-step entre parentesis):**

| Config | 2018-26 realistic | 2020-26 realistic | 2018-26 CONSERVATIVE |
|---|---|---|---|
| E9 r1.0% | 0.610/0.297 (0.703/0.229) | 0.452/0.413 (0.589/0.310) | 0.371/0.341 (0.580/0.278) |
| E9 r1.25% | 0.643/0.307 (0.730/0.265) | 0.550/0.422 (0.654/0.339) | 0.437/0.327 (0.599/0.303) |

Cero violaciones de la regla 3%/trade; worst daily DD 2.7-2.8% (el daily nunca muerde).
maxDD del motor 19-26% — una cuenta funded (techo 6-10%) muere eventualmente; el EV
funded es "payouts hasta el blowup", no renta perpetua.

**VEREDICTO: NO-GO — NO comprar challenge.** Los criterios de FASE 7 exigen P(pasar)
>=60% CON COSTES CONSERVADORES y P(breach) <=20%. Con conservative (slippage 3x, mas
duro que el x2 exigido): two-step 37-44%, one-step 58-60%, y breach 27-42% en todas las
celdas — ambos criterios fallan. El 60%+ solo existe con costes realistic en la ventana
ya sobre-explotada. Ademas el FUNDING de perps NO esta modelado (notional 50%, holds
multi-dia: ~1.5-2.5%/anio de drag en longs) — solo empeoraria.

**Balance del proyecto:** de 11.8% (E6) a 73%/64% realistic (E9 r1.25) — el motor es
real (PF 1.14 conservative, +39%/8a) pero fragil a costes, y la economia del challenge
no cierra bajo supuestos honestos. Hallazgos estructurales que quedan: (1) shorts BTC
= la mitad del edge; (2) ETH inerte con este motor; (3) la regla letal es el max loss
total, no el daily DD; (4) Swing Upgrade inutil para este motor; (5) el cap de notional
clampeaba el riesgo — cualquier motor futuro debe verificar sizing efectivo vs
configurado.

**Condiciones de reapertura (todas, no alguna):** modelo Bybit real (fees maker/taker,
funding historico, spread) integrado en el backtest; y un motor que de two-step >=60% /
breach <=20% bajo ese modelo CON conservative. Sin eso, esta linea queda CERRADA.
Config E9 congelada y reproducible:
`--config '{"entry_mode":"breakout","risk_per_trade":0.0125,"tp1_r":1.5,"allow_shorts":true,"max_notional_pct":0.5}'`.
[2026-07-03: Matias decide NO cerrar — reapertura via PLAN B, seccion 13.]

---

## 13. PLAN B — REMAKE (2026-07-03, sesion 17 bis; decision de Matias: no matar el proyecto)

Premisa corregida antes de disenar: una prop firm es rentable vendiendo challenges a
gente que falla — su existencia NO demuestra que pasar sea sistematicamente alcanzable.
Lo que SI es verdad: (a) nuestro no-go se decidio por SUPUESTOS de coste (conservative
15bps), no por costes medidos; (b) el unico gap real es expectancy del motor — el risk
management esta RESUELTO (daily DD, 3%/trade, distribucion, margen: todo verde). El
remake ataca expectancy y sustituye supuestos por medidas.

- **N0 — Medir la realidad antes de redisenar (EN PARALELO, coste ~0, 2-4 semanas).**
  Bybit testnet con E9 congelado. El no-go realistic->conservative es una disputa de
  10bps de slippage: BTC perp con ordenes de $3-6k tiene spread ~1bp y book profundo.
  Medir slippage real por orden, fees efectivas, funding pagado/cobrado (reusar patron
  parity-check F15). DECISION CON DATOS: coste real <=7bps por lado -> E9 one-step
  (0.599-0.730 pass) se re-evalua como candidato de compra directo; >=12bps -> el
  remake es obligatorio y N0 calibra el modelo de N1.
- **N1 — Modelo Bybit en el backtest** (= condicion de reapertura de seccion 12): fees
  maker/taker Bybit, funding historico (reusar `funding_context`), spread. Todos los
  gates futuros se evaluan bajo este modelo.
- **N2 — Screens de alfa NO-indicador con datos YA disponibles (barato, sin estrategia
  nueva todavia).** Sobre el cache 1H 2014-2026 y funding_context:
  (a) estacionalidad intradia/semanal (sesiones US/EU/Asia, dia de semana, fin de semana);
  (b) funding extremo como senal (crowding: funding p95+ -> squeeze de longs);
  (c) drift alrededor de settlements de funding (00/08/16 UTC);
  (d) reversion post-barrida (barras 1H con rango >p99: continuacion o reversion).
  Metodo: expectancy condicional vs incondicional por anio (estabilidad temporal, no
  t-stat de una ventana). Gate: efecto estable en >=6 de 8 anios -> pasa a motor N4.
- **N3 — Datos derivados nuevos (OI, liquidaciones, basis)** — SOLO si N2 no da nada y
  N0 justifica seguir: evaluar coste/factibilidad primero (Bybit API tiene poco
  historico; archivos completos suelen ser de pago).
- **N4 — Motores candidatos** desde lo que sobreviva de N2/N3, cada uno AISLADO por el
  simulador bajo modelo N1. Gates: two-step >=60% / breach <=20% con conservative-N1.
- **N5 — Meta-labeling sobre E8/E9** (filtrar los trades del breakout con features de
  contexto: funding, vol percentile, sesion, distancia a EMA; walk-forward con embargo).
  ULTIMO recurso: maximo riesgo de overfit-hunting del proyecto entero.
- **Presupuesto duro:** N0 corre en paralelo y es casi gratis. Si tras N2 (y N3 si se
  aprueba) ningun efecto pasa su gate Y N0 da costes reales >=12bps -> cierre sin
  apelacion. No hay N6.

### N2 — EJECUTADO (2026-07-03, `tools/alpha_screens.py`)

BTC 1H 2015-2026 (96930 barras) + funding Bybit por settlement (6874, 2020-03 -> hoy,
cache `data/cache/funding_bybit_BTCUSDT.json`). Barra de tradability standalone ~30bps.
LECCION METODOLOGICA: reportar SIEMPRE con dedup de senales solapadas — el screen D
paso de +157bps (10/11 anios) a +19bps (5/11) al deduplicar: las cascadas de un crash
cuentan N veces el mismo rebote. Toda senal densa en el tiempo debe deduplicarse antes
de creersela.

| Screen | Resultado (dedup) | Veredicto |
|---|---|---|
| A) Hora del dia | max h21 +4.6bps (11/12 anios) | NO tradable (10x bajo la barra) |
| C) Dia de semana | Lun +46 / Mie +36 / Vie +37 bps (8-9/11) | Marginal; solo micro-filtro |
| D) Post-barrida 1H >p99 | f24 +19bps, WR 53%, 5-6/11 anios | MUERTO (artefacto de clustering) |
| B) Funding extremo trailing p95/p05 | ver abajo | **UNICO SUPERVIVIENTE — pasa gate** |

**B en detalle (dedup >72h entre senales, horizonte 72h):**
- funding>p95 (longs crowded): n=54 (~9/anio), f72 media +144 / mediana +92 bps,
  WR 65%, **6/6 anios positivos**. OJO: f24 mediana -16 (el efecto tarda ~1 dia en
  arrancar — detalle de diseno para N4).
- funding<p05 (shorts crowded, squeeze): n=126 (~21/anio), f72 media +108 / mediana
  +58 bps, WR 60%, 5/6 anios.
- Ambas colas son LONG a 72h. Sin senal short en este screen. Solo 6 anios de datos
  (Bybit 2020+), regimen mayormente alcista — control pendiente en N4: exceso sobre
  base f72 (~+51bps) y comportamiento 2022.

**Consecuencia -> N4:** un solo motor candidato: "funding-extreme long" (entrada tras
extremo de funding deduplicado, hold ~72h con stop, posible retraso de entrada 24h en
la cola p95). ~30 senales/anio. Debe medirse por el simulador prop; N1 (modelo Bybit
con funding) es prerequisito para el veredicto final.

---

## 14. E9 COMO ESTRATEGIA STANDALONE — COMPARATIVA vs SWING v5 (2026-07-03)

Peticion de Matias: medir si E9 es rentable "como tal" (capital propio), mismas ventanas
y ruta CLI que las anclas del Swing. Backtests `main.py backtest --strategy prop
--costs realistic` con config E9. Journals:
`journal_prop_swing_..._20260703_171030.json` (2018) / `..._171449.json` (2015).

| Metrica (realistic) | Swing v5 2015-26 | E9 2015-26 | Swing v5 2018-26 | E9 2018-26 |
|---|---|---|---|---|
| Balance final ($10k) | $9.164M (CLI) | $26,347 | $219.8k | $16,275 |
| CAGR | +85.9% | +9.2% | +47.1% | +6.3% |
| Max DD | -52.73% | -21.19% | -53.72% | -21.19% |
| Calmar | 1.63 | 0.43 | 0.88 | 0.30 |
| Sharpe / Sortino | 1.38 / 1.57 | 0.63 / 0.90 | — | 0.30 / 0.44 |
| Underwater max | 922 d | 658 d | — | 658 d |
| Tiempo en mercado | 100% | 15.8% | 100% | 14.7% |
| Posiciones | 70 rebal. | 259 (190L/69S) | 53 rebal. | 183+shorts |
| B&H ventana | +27,653% | +27,653% | +549% | +549% |

PnL por anio E9 2015-26 (nivel posicion, shorts incluidos): 10/11 anios positivos;
2022 = 2o mejor anio (+$4,263, los shorts entregan en bear). **2025 = unico anio
negativo (-$3,963)**; el Max DD -21.19% es exactamente Q1-2024 -> finales-2025 (654d
peak->trough): el peor tramo historico del motor es EL MAS RECIENTE (mercado en rango
2024-25 tritura breakouts en ambas direcciones).

**Conclusiones:**
1. E9 es rentable standalone (CAGR +9.2%, 10/11 anios verdes) pero NO competitivo como
   vehiculo de capital propio: el Swing lo domina TAMBIEN ajustado a riesgo (Calmar
   1.63 vs 0.43, Sharpe 1.38 vs 0.63). Con capital propio, E9 no tiene rol.
2. El valor de E9 es exclusivamente prop: DD -21% y daily DD max 2.8% son inaceptables
   de superar para reglas prop, y el apalancamiento ajeno multiplica su CAGR modesto.
3. ALERTA para la decision de compra: la degradacion 2024-2025 significa que los pass
   rates @540d beben sobre todo de ventanas 2018-2023. Un challenge comprado HOY entra
   en el regimen que peor le sienta al motor. Refuerza N0 (medir antes de comprar) y
   pide un degradation-check tipo F19 para E9 si algun dia opera.
4. Nota tecnica: el resumen trimestral del CLI solo ve patas long (los shorts sinteticos
   no pasan por el pairing ACB); el PnL por anio del journal (true_pnl_usdt) es la vista
   completa. Metricas de equity (CAGR/DD/Sharpe) correctas en ambas rutas.

---

## 15. N4 — MOTOR "FUNDING-EXTREME LONG" MEDIDO Y RECHAZADO COMO PROP (2026-07-04, sesion 18)

Implementado `strategies/funding_extreme.py` (registry `funding`) desde el unico superviviente
de N2. Senal por settlement Bybit, percentil trailing 90 settlements shift(1) (anti-lookahead),
dedup conjunto 72h, delay 24h en cola p95 (hallazgo f24 negativo), hold 72h, stop 2xATR14-4H,
sizing riesgo 1% cap notional 0.5 (esquema E9). MODELO N1 nuevo en `core/backtest.py`: costes
`bybit` (taker 5.5bps + 2bps slip) y `bybit_cons` (5.5 + 10bps); **funding devengado por
settlement** dentro del motor via adjust_balance (la cola p95 entra pagando funding caro).
Ventana 2020-06 -> 2026-01 (Bybit funding empieza 2020-03). 277 senales dedup (86 hi / 191 lo),
238 trades con PnL.

**Edge standalone (bueno): rentable y DD bajo.**
- bybit: pnl +71.96% | PF 1.44 | WR 50.0% | expectancy +30bps | maxDD **12.96%**.
- bybit_cons: pnl +53.68% | PF 1.34 | WR 48.7% | expectancy +23bps | maxDD 13.91%.
El perfil de bajo DD es lo contrario de E9 (-21%). El screen N2 se confirma como efecto real.

**Como PROP: RECHAZADO — no pasa el gate (>=60% pass / <=20% breach) en ninguna variante.**
| costes | config | pass | breach | timeout |
|---|---|---|---|---|
| bybit | two_step_swing | 0.362 | 0.342 | 0.296 |
| bybit | one_step_swing | 0.531 | 0.369 | 0.100 |
| bybit_cons (gate) | two_step_swing | **0.271** | **0.367** | 0.362 |
| bybit_cons (gate) | one_step_swing | 0.418 | 0.458 | 0.124 |

Peor que E9 (two-step 64% realistic / 37-44% conservative). Los breaches son mitad daily,
mitad total, + muchos `trade_loss_violation` (45-48 en two-step): trades sueltos que exceden
el limite de perdida por trade del prop pese al risk 1%. El motor con hold fijo de 72h y stop
2xATR no controla el daily DD lo bastante para el challenge.

**Diagnostico: mismo patron del proyecto entero.** Hay edge (positivo, robusto, DD bajo) pero
la distribucion no cabe en las reglas prop. N2->N4 agota el frente de alfa no-indicador barato.

**Estado del PLAN B tras N4:**
- N2 (screens) y N4 (motor del superviviente) EJECUTADOS y sin candidato que pase el gate.
- Presupuesto duro (seccion 13): "si tras N2 ningun efecto pasa su gate Y N0 da costes reales
  >=12bps -> cierre sin apelacion". N4 no pasa. Falta SOLO N0 (testnet Bybit, BLOQUEADO en
  Matias: cuenta + API keys) para el cierre formal. Si N0 mide costes <=7bps, E9 one-step
  (0.60-0.73 realistic) se re-evalua; si >=12bps, cierre.
- N3 (OI/liquidaciones/basis) y N5 (meta-labeling) NO ejecutados: solo tendrian sentido si
  N0 justifica seguir invirtiendo, y N5 es el de mayor riesgo de overfit del proyecto.

**Valor residual de funding_extreme (no-prop):** rentable con DD 13%, pero como capital propio
esta dominado por el Swing v5 igual que E9 (mismo argumento de la seccion 14). No adoptar como
vehiculo propio. Queda en el registry, reversible y medido, por si N0/N1 reabren el frente.

---

## 16. N0-LITE — COSTE PUBLICO BYBIT SIN CUENTA (2026-07-04)

Peticion de Matias: ir al punto 3 antes de abrir cuenta. Implementado
`tools/bybit_public_cost_probe.py`: consulta solo el order book publico de Bybit
BTCUSDT linear perp, sin API key, y calcula coste estimado de cruzar mercado contra el
mid para tamanos E9.

Muestra ejecutada: 12 snapshots, 5s entre snapshots, 2026-07-04 11:02:42 -> 11:03:39
UTC. Output guardado en `data/runtime/bybit_public_cost_probe_latest.json` (runtime,
no versionado).

| Metrica | Resultado |
|---|---:|
| Mid p50 | 62,455.85 |
| Spread p50 / p95 | 0.016 / 0.016 bps |
| Profundidad p50 dentro de 1bp, lado debil | ~703k USDT |
| Profundidad p50 dentro de 2bp, lado debil | ~1.70M USDT |
| Profundidad p50 dentro de 5bp, lado debil | ~6.03M USDT |
| Profundidad p50 dentro de 10bp, lado debil | ~13.33M USDT |

Coste estimado por market order, contra mid, incluyendo taker fee VIP0 5.5bps:

| Notional | Slip p95 peor lado | Coste taker total p95 |
|---:|---:|---:|
| 1k USDT | 0.008 bps | 5.508 bps |
| 3k USDT | 0.008 bps | 5.508 bps |
| 6k USDT | 0.008 bps | 5.508 bps |
| 12.5k USDT | 0.008 bps | 5.508 bps |
| 25k USDT | 0.044 bps | 5.544 bps |

**Lectura:** para tamanos E9 ($3k-$12.5k, incluso $25k), el libro publico actual es
suficientemente profundo. El supuesto `--costs bybit` (5.5bps fee + 2bps slip = 7.5bps)
queda conservador frente a esta muestra. `bybit_cons` (5.5+10bps) sigue siendo stress,
no base case.

**Limites:** esto NO mide fills reales, latencia, rechazos, partial fills, momentos de
noticias, ni la capa Hyro/Tealstreet/CLEO. Tampoco resuelve funding historico de E9:
el probe solo responde a spread/profundidad actual. El N0 formal con cuenta/terminal
sigue siendo necesario antes de operar dinero o comprar challenge, pero ya no hace
falta para defender que el libro BTCUSDT puede soportar los tamanos E9.

**Implicacion de decision:** el cierre por "costes >=12bps" NO queda apoyado por datos
publicos de libro en condiciones normales. Si se reabre E9, la siguiente medicion debe
ser E9 bajo `--costs bybit` + funding historico para PropSwing, y solo despues decidir
si merece una prueba Hyro/terminal.

---

## 17. E9 + FUNDING Y COMPARATIVA PROP FIRMS (2026-07-04)

Implementado: `BacktestClient.get_ohlcv` cacheado (runner E9 deja de atascarse),
`PropSwingConfig.model_funding` (default False, activar en decision), y `--rules
hyro|breakout|cft` en `tools/prop_challenge_sim.py`. Tests: 125/125.

Config E9+funding: `{"entry_mode":"breakout","risk_per_trade":0.0125,"tp1_r":1.5,
"allow_shorts":true,"max_notional_pct":0.5,"model_funding":true}`.

| Ventana/coste | Hyro one-step | Hyro two-step |
|---|---:|---:|
| 2018-26 bybit | 75.7% / 23.1% | 68.9% / 24.1% |
| 2018-26 bybit_cons | 74.0% / 25.6% | 68.1% / 26.3% |
| 2020-26 bybit | 68.4% / 30.6% | 57.6% / 32.1% |
| 2020-26 bybit_cons | 67.4% / 32.2% | 60.3% / 36.2% |

Lectura: costes reales baratos SI reabren E9 estadisticamente, pero NO dan go directo:
pass >60% en varias celdas, breach sigue >20% y 2024-26 aislado es malo (-7.4%, one-step
4.3%, two-step 0%). El cuello es max loss total, no daily.

Comparativa externa simulada con E9+bybit+funding:
- **Breakout** (Classic/Pro/Turbo): 2018-26 = 59/41, 55/45, 43/58; 2020-26 = 47/53,
  43/57, 39/61. Descartado para E9: daily 3% muerde demasiado.
- **Crypto Fund Trader 2-phase** (8%+5%, 5d, 5% daily/10% total, sin distribucion en
  el sim): 2018-26 = 73.7/22.3; 2020-26 = 64.1/30.0. Mejor rule-set, pero breach aun alto
  y Bybit personal mantiene riesgo jurisdiccional; Match/MT5 no replica perps/funding.
- **Phase-router CFT**: `entry_halving_phases="bear_onset,accumulation"` + r1.8/n0.8
  bajo `bybit_cons` pasa stress: 2020-26 74.8/2.0; shift -60 74.2/16.0; 2018 shift
  -60 71.9/13.9. Candidato vivo, CFT-only; Hyro sigue fuera por breach/trade loss.
- **Manual Breakout**: viable solo como plan de senales propias + ejecucion manual, pero
  hay que confirmar soporte/API/bots y que una alerta de sistema propio no se considere
  senal de tercero. No comprar sin confirmacion escrita.
