# AUDITORIA POST-IMPLEMENTACION — Swing Allocator v5 (2026-07-02)

Auditoria del diff completo desde el tag `swing-v4-frozen` (06395ff): cambios F1-F19 del
`PLAN_MEJORA_AUDITORIA.md`. Objetivo: verificar que los fixes NO introducen sesgos nuevos
(lookahead, leakage, costes, timezone, gaps) y que los hallazgos B1-B5/C1-C9 de
`AUDITORIA_SWING_V4.md` quedaron resueltos.

**Alcance:** `core/backtest.py`, `core/exchange.py`, `main.py`, `strategies/macro_context.py`,
`strategies/swing_allocator.py`, tests y `tools/` nuevos. El nucleo de decision del Swing
(v4 estructural) NO se re-audita: quedo auditado en `AUDITORIA_SWING_V4.md` y esta congelado.

**Definicion de v5:** v4 estructural + `daily_on_closed_only=True` (F8 — UNICO delta de
comportamiento). El resto de cambios son motor/metricas/operativa live y no tocan senales.

---

## VEREDICTO GLOBAL

**APTO PARA FREEZE.** Ningun hallazgo CRITICO ni ALTO. Los cambios F1-F19 no introducen
lookahead ni leakage; los dos unicos deltas que tocan la simulacion (F8 y el coste del B&H F11)
van en direccion CONSERVADORA (empeoran ligeramente al Swing / al benchmark de forma justa).
Quedan 2 hallazgos MEDIO (riesgo latente, no activo en el dataset canonico) y 4 BAJO.

Tests: 88/88 en verde (`python -m pytest tests -q`), incluyendo `test_backtest_pnl.py` (F1)
y `test_swing_allocator_controls.py` (F14).

---

## HALLAZGOS NUEVOS (introducidos por la implementacion)

### M1. [MEDIO] `set_phase_bounds` muta estado GLOBAL de modulo desde el constructor del bot

- **Donde:** `strategies/swing_allocator.py` (`SwingAllocatorBot.__init__`) →
  `strategies/macro_context.py` (`set_phase_bounds`, globales `PHASE_*`).
- **Que pasa:** cada instancia del Swing re-escribe los umbrales de fase PARA TODO EL PROCESO.
  `halving_phase` tambien lo consume Pro Trend: un Swing con fases custom (sensitivity) cambiaria
  las fases de Pro Trend en el mismo proceso. Dos backtests Swing concurrentes con fases distintas
  en un mismo proceso se pisarian.
- **Por que no es ALTO:** en produccion los defaults son identicos (180/540/900) y el setter es
  no-op + hay warning log si se cambian. Solo afecta a harnesses de sensitivity multi-config
  en proceso unico.
- **Accion recomendada (no urgente):** pasar los umbrales por parametro a `get_macro_signal`
  en vez de globales, o documentar "un proceso = una config de fases" en los tools (hoy los
  tools cumplen esto).

### M2. [MEDIO] El filtro de tick anomalo (F14) corre TAMBIEN en backtest

- **Donde:** `strategies/swing_allocator.py` (`_market_data_ok`), llamado antes de `_initialize`
  y de cada evaluacion; `max_price_jump_pct=0.25` aplica igual con `BacktestClient`.
- **Medicion (2026-07-02):** salto 1H maximo close-to-close en el dataset canonico BTC
  (102931 velas) = **19.18%** (2020-03-12 10:00, COVID) → el filtro NUNCA dispara en BTC
  2015-2026. En el cache ETH-USDT el maximo es **24.07%** (2020-03-12 10:00) — a 0.9pp del
  umbral. Las anclas v5 NO estan afectadas.
- **Riesgo latente:** en otro dataset (ETH con otro gap-fill, otro activo, otro rango) el filtro
  podria SALTARSE en silencio la barra de decision de un crash dentro del backtest — un cambio de
  comportamiento que nunca se midio aislado (rompe el protocolo).
- **Accion recomendada:** limitar el rechazo por salto a clientes live/paper (como ya hace la rama
  "OHLCV insuficiente"), o como minimo loggear + contar disparos en backtest. Mientras tanto:
  si un backtest futuro muestra rebalanceos "ausentes" en un crash, revisar esto primero.

### B1n. [BAJO] `fill_next_open=True`: compra con gap alcista puede rechazarse en silencio

- **Donde:** `core/backtest.py` (`_fill_market` + branch buy "Saldo insuficiente").
- **Que pasa:** el sizing se calcula contra el close de la barra de decision con buffer 0.35%;
  si el open siguiente gapea por encima del buffer, la orden se rechaza sin log visible y la
  medicion pierde ese rebalanceo. Ademas, en la ultima barra cae de vuelta al fill al close.
- **Por que BAJO:** `fill_next_open` es solo modo de MEDICION (default False, F10 no adoptado).
- **Accion:** si se vuelve a usar para medir, contar rechazos y reportarlos.

### B2n. [BAJO] `OKXClient.get_ohlcv` conserva la vela en curso (confirm flag descartado)

- **Donde:** `core/exchange.py` (paginacion F12) — se descarta la columna `confirm` de OKX sin
  filtrar velas no confirmadas (igual que el codigo anterior).
- **Por que BAJO:** los consumidores ya se protegen: Swing excluye el dia en curso
  (`daily_on_closed_only`), Pro Trend excluye el bloque 4H incompleto. Sin sesgo hoy.
- **Accion:** si se anade un consumidor nuevo de OHLCV live, recordar que la ultima fila puede
  ser una vela parcial (documentado aqui).

### B3n. [BAJO] Dos referencias "v4 congelado" difieren ~0.3% entre etapas de medicion

- Smoke CLI post-F1/F2: final $9.307M / CAGR +86.2%. Baseline tools F5/F8:
  $9.28M / +86.11%. Mismo warmup nominal (250d), misma config. Drift sin atribuir
  (probable diferencia menor de harness CLI vs tools).
- **Por que BAJO:** no afecta a las anclas v5, que se definen con UN solo harness
  (`tools/swing_v5_freeze_report.py`, mismo patron que el resto de tools). CAGR/DD coinciden
  al primer decimal en todas las mediciones.
- **Accion:** las anclas oficiales v5 son las del freeze report. No comparar finales absolutos
  entre harnesses distintos.

### B4n. [BAJO] `_compute_trade_pnl_acb` descarta ventas sin posicion sin contarlas

- **Donde:** `core/backtest.py` (`continue` en la rama sell con `qty_open <= 0`).
- **Por que BAJO:** solo aplicaria a cortos sinteticos (`allow_shorts`, irrelevante para Swing y
  para Pro Trend default). Si algun dia se auditan metricas con shorts, este metodo los ignora.

---

## VERIFICACION PUNTO POR PUNTO (protocolo /audit-backtest)

### 1. Lookahead — SIN HALLAZGOS NUEVOS ✅

- **F8 verificado correcto:** `resample_to_daily` etiqueta por INICIO de dia (resample "1D",
  label left) y el corte es estricto (`daily["dt"] < current_day`) → el dia parcial en curso
  queda SIEMPRE excluido de ema50d/ema200d/rsi/adx/pi_cycle con el flag True. La fecha de corte
  sale del open de la barra actual (conservador).
- `BacktestClient.get_ohlcv` entrega hasta la barra actual inclusive; la decision se toma al
  close de esa barra 1H (cerrada). Sin cambio vs v4.
- `_market_data_ok` usa `iloc[-2]` (barra anterior cerrada) vs ticker actual — no mira futuro.
- F10 `fill_next_open` usa el open de la barra siguiente SOLO para el fill (anti-lookahead por
  construccion); default False.
- Offsets de contexto externo (MVRV dia anterior, VIX/DXY/NDX sesion anterior, funding dia
  completo anterior): NO tocados por el diff — verificados intactos en `macro_context._lookup`
  y companeros.

### 2. Leakage — SIN HALLAZGOS ✅

- Warmup excluido de simulacion y benchmark (`bars[self._warmup]` como primer precio B&H;
  equity solo post-warmup). Sin shift negativo ni resample con label derecho en el diff.
- F4 (`set_phase_bounds`): defaults reproducen el comportamiento historico EXACTO; validacion
  `0 < post < peak < onset` y warning si se cambian. El riesgo es el estado global (M1), no leakage
  temporal.

### 3. Costes — SIN HALLAZGOS ✅

- Fee 0.1% en CADA fill: compra `cost = size*price + fee`; venta `proceeds = size*price - fee`.
- F1 (ACB) es contable puro: fee de compra capitalizada en el coste medio, fee de venta prorrateada
  si la cantidad se recorta. La equity NO cambia (verificado: mismas anclas con acb/legacy).
- F11: el B&H ahora paga fee+slippage de su unica compra — direccion JUSTA (endurece el benchmark
  de la misma forma que la estrategia paga sus fills).

### 4. Slippage — SIN HALLAZGOS ✅

- Aplicado por modo (0/5/15 bps) sobre el precio raw en `_fill_market`, sentido correcto
  (buy paga mas, sell recibe menos). Buffer 0.35% de los rebalanceos intacto.

### 5. Timezone — SIN HALLAZGOS ✅

- Todos los timestamps nuevos tz-aware UTC (`datetime.fromtimestamp(..., tz=timezone.utc)`,
  `pd.Timestamp(..., tz="UTC")`). `get_ohlcv` live devuelve ms int64 UTC identico al backtest.
  Sin conversiones a local en rutas de calculo.

### 6. Gaps — SIN HALLAZGOS ✅

- Dataset canonico 102931 velas: continuo, cero huecos >24h (validado en adopcion 2026-07-02).
- La paginacion live (F12) deduplica por timestamp y ordena ascendente; no fabrica velas.

### 7. Overfitting — SIN HALLAZGOS ✅ (con nota)

- v5 NO anade ningun threshold fitted: `daily_on_closed_only=True` se adopto POR HIGIENE
  costando -0.27pp CAGR (direccion opuesta a overfitting). F9/F10 se midieron y NO se adoptaron
  pese a ser neutros — protocolo respetado.
- `max_price_jump_pct=0.25` es un threshold nuevo con justificacion estructural (control
  operativo live anti flash-crash/fat-finger), inerte en los datasets actuales — pero ver M2.
- La ventana 2015-2026 sigue CERRADA (regla invariante #5); F5/F6/F7 solo MIDIERON.

---

## RESOLUCION DE HALLAZGOS DE LA AUDITORIA V4

| Hallazgo v4 | Fix | Estado verificado en codigo |
|---|---|---|
| B1/B2 calendario halving hardcoded/fragil | F4 + F5 | ✅ parametrizado con defaults exactos; fragilidad medida y documentada (shift -60d: +72.86% CAGR; +60d: DD -66.08%). No resuelto de raiz — es fragilidad del EDGE, no del codigo; queda como riesgo conocido |
| B3 P&L por trade roto (pairing sin igualar qty) | F1 | ✅ ACB con fees prorrateados; equity identica; PF sigue NO-ancla |
| B4 paridad live rota (get_ohlcv 300, sin ruta start) | F12/F13/F14/F15 | ✅ paginado int64 + ruta start + RiskManager + controles; PENDIENTE cierre real: 24h runtime y paridad 30d (requieren paper) |
| B5 data snooping de proceso | 0.2 | ✅ regla invariante #5 en SESSION.md; ventana cerrada |
| C1 fill al close de la decision | F10 | ✅ medido (+86.08% vs +86.11%): optimismo despreciable; default sin cambio |
| C2 indicadores diarios con dia parcial | F8 | ✅ ADOPTADO (el delta v5); verificado sin off-by-one |
| C3 riesgo USDT | F16 | ✅ stress -5/-10% medido; riesgo aceptado con sizing/custodia prudente |
| C4 underwater infrarreportado | F2 | ✅ `underwater_days` peak→recovery (922d) junto a peak→trough (260d) |
| C6 cadencia dependiente del offset | F9 | ✅ medido, NO adoptado (no mejora); sensibilidad documentada |
| C7 EMA200D truncada sin documentar | F11 | ✅ comentario en config |
| C8 sizing sin base formal | F7+F17 | ✅ bootstrap x1000 (DD p95 -68.31% / p99 -74.34%) + marcos de sizing en SESSION.md |
| C9 B&H sin costes | F11 | ✅ fee+slip de entrada aplicados al benchmark |

---

## ANCLAS v5 (re-verificadas en el freeze, `tools/swing_v5_freeze_report.py`)

| Ventana | Costes | Final | CAGR | Max DD | Rebalances | btc_vs_bnh |
|---|---|---:|---:|---:|---:|---:|
| BTC 2015-2026 | realistic | $9,137,545.81 | +85.84% | -52.73% | 70 | 0.8171 |
| BTC 2018-2026 | realistic | $219,763.03 | +47.14% | -53.72% | 53 | 0.8432 |
| BTC 2015-2026 | conservative | $8,897,454.17 | +85.40% | -52.88% | 70 | 0.7961 |

Secundarias (2015-26 realistic / 2018-26 realistic / 2015-26 conservative):
Calmar 1.63 / 0.88 / 1.61 · Sharpe 1.38 / 1.00 / 1.37 · Sortino 1.57 / 1.18 / 1.57 ·
underwater max 922d en las tres (mismo periodo 2021-2024). PF ACB 78.5 / 67.4 / 75.1 —
contable, NO ancla.

Re-verificacion ejecutada 2026-07-02 al cierre del freeze (exit 0, coincidencia exacta con los
valores del freeze de la sesion anterior). Coste del fix anti-lookahead (F8) vs v4 congelado:
-0.27pp CAGR / -0.02pp DD. Rollback exacto a v4: `--config '{"daily_on_closed_only": false}'`.

---

## CONCLUSION

v5 queda congelado como default. Los hallazgos M1/M2 son riesgo LATENTE (inertes en los datos
actuales) y no bloquean el freeze; quedan anotados para resolverse si se reabre codigo. El
siguiente hito NO es mas backtest: validacion forward/paper (cierra F13/F15/F19). La fragilidad
del calendario de halving (B2) sigue siendo el riesgo estructural #1 del edge y solo el forward
puede des-riesgarla.
