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
