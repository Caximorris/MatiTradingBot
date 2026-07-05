# Swing Allocator v6 — Plan de Investigacion desde PropSwing/CFT

**Fecha:** 2026-07-05  
**Estado:** PLANNING. No cambia el default.  
**Baseline vigente:** Swing Allocator v5 post-audit, congelado.  
**Objetivo:** definir si las lecciones de PropSwing/CFT pueden convertirse en un Swing v6 con
mejores resultados reales sin romper la tesis principal: acumular BTC y mantener una sola
estrategia BTC/USDT spot.

---

## 0. Respuesta corta

[Likely] Si se puede aprovechar parte de lo aprendido en PropSwing, pero no copiando la estrategia
de prop firm. PropSwing es un motor discreto 4H para pasar challenges; Swing Allocator es un
allocator spot long-only. Lo transferible es el **metodo**: phase-router, analisis por ventanas de
inicio, deduplicacion de senales, funding extremo como alfa candidato y monitorizacion de
degradacion.

[Certain] No hay permiso metodologico para promover v6 solo porque mejore 2015-2026. Esa ventana
esta cerrada para optimizacion. Cualquier v6 debe:

- no empeorar las anclas v5 en ventanas cerradas;
- aportar evidencia estructural o forward/paper posterior a 2026-01-01;
- mantener `btc_vs_bnh_ratio` como metrica primaria junto a CAGR y Max DD;
- ser reversible por config.

[Likely] Las vias vivas para v6 son dos:

1. **Phase policy router:** formalizar la logica por fase como matriz/politica, no como flags
   acumulados. Primero debe reproducir v5 exacto.
2. **Funding extreme overlay:** usar el unico alfa no-indicador que sobrevivio en PropSwing como
   modificador pequeno de allocation, no como estrategia separada.

---

## 1. Baseline v5 que v6 debe respetar

Anclas documentadas, dataset canonico 102931:

| Config | Ventana | Costes | Final | CAGR | Max DD | Rebalances | BTC vs B&H |
|---|---|---:|---:|---:|---:|---:|---:|
| Swing v5 | 2015-2026 | realistic | $9.137M | +85.84% | -52.73% | 70 | 0.8171 |
| Swing v5 | 2018-2026 | realistic | $219.8k | +47.14% | -53.72% | 53 | 0.8432 |
| Swing v5 | 2015-2026 | conservative | $8.897M | +85.40% | -52.88% | 70 | 0.7961 |

Smoke por CLI puede dar $9.164M en 2015-26 realistic por diferencia de warmup; no es regresion.
El documento de v6 debe comparar por la misma ruta/tool en cada matriz.

---

## 2. Que se aprendio de PropSwing y que se transfiere

| Leccion PropSwing/CFT | Transferible a Swing v6 | Uso propuesto | Riesgo |
|---|---|---|---|
| Phase-router mejora al operar solo `bear_onset/accumulation` en CFT | Si, como metodologia | Validar candidatos por fase de inicio y sensibilidad de calendario | Sobreajustar umbrales 180/540/900 |
| `start_filter` por fase cambia radicalmente pass/breach | Si | Crear matrices de inicio/offset para Swing, no solo una fecha fija | Mezclar ventanas con distinto conteo de velas |
| Funding extremo fue el unico alfa no-indicador vivo | Si, con cautela | Overlay pequeno `+0.05/+0.10` de target, deduplicado | Funding perps puede no mapear a spot allocator |
| Deduplicar senales solapadas fue obligatorio | Si | Todo screen v6 debe deduplicar eventos antes de medir forward returns | Inflar edge por senales repetidas |
| 2024-2025 fue degradacion real del motor prop | Si, como alerta | Añadir reporte de degradacion por regimen/fase/actividad | Optimizar para arreglar solo 2025 |
| Monitor CFT hard-stop | Parcial | Usar como telemetria/riesgo operativo, no como alpha | Convertir Swing en stop-loss discreto y romper tesis |
| Shorts sinteticos mejoran prop pass-rate | No por defecto | No meter shorts en Swing v6 | Cambia producto, custodia y perfil fiscal/riesgo |
| Breakout Donchian 4H viable para challenge | No directamente | Solo como screen auxiliar, no como allocator default | Convertir Swing en ProTrend/PropSwing encubierto |

---

## 3. Hipotesis v6

### H1 — Phase Policy Router

[Likely] El Swing actual ya es phase-aware, pero esta expresado como suma de flags y deltas. v6
puede mejorar mantenibilidad y robustez convirtiendo la logica en una tabla de politicas por fase.

Primero debe existir una politica `v5_equiv` que reproduzca v5 exactamente:

| Fase | Regime bull | Neutral | Regime bear | Notas |
|---|---:|---:|---:|---|
| post_halving | 1.00 | 0.80 | 0.60 | base 0.60 + halving 0.20 + regime |
| bull_peak | 1.00 | 0.80 | 0.60 | cap 0.85 si pierde EMA50D cerrada |
| bear_onset | 0.30 | 0.30 | 0.20 | bull suprimido; bear clamped por floor |
| accumulation | 0.80 | 0.60 | 0.40 | sin delta halving actual |

Candidatos estructurales despues de reproducir v5:

| ID | Cambio | Razon | Parametros |
|---|---|---|---|
| H1-A | `accumulation_bear_target` 0.40 -> 0.35/0.30 | Acumular USDT si el bear sigue vivo incluso en accumulation | solo si no mata BTC vs B&H |
| H1-B | `bull_peak_neutral_target` 0.80 -> 0.75/0.70 | Reducir exposicion cuando el ciclo esta avanzado pero sin regimen claro | debe sobrevivir 2017/2021 |
| H1-C | `post_halving_bear_target` 0.60 -> 0.55/0.50 | Evitar quedar demasiado expuesto si el mercado falla temprano | probable coste de CAGR |
| H1-D | `phase_policy_compact` | Refactor sin cambio de comportamiento | debe dar paridad exacta vs v5 |

Veredicto inicial: `NEEDS_MORE_VALIDATION`. No adoptar por backtest cerrado.

### H2 — Funding Extreme Overlay

[Likely] Es el candidato de alpha mas interesante del trabajo prop. En `alpha_screens.py`,
funding extremo fue el unico patron no-indicador que sobrevivio a deduplicacion. En vez de operar
trades discretos, v6 lo usaria como ajuste temporal de allocation.

Regla candidata:

```text
if use_funding_overlay:
    signal = funding percentile closed-only
    if signal extreme and not duplicated within N days:
        target += funding_overlay_delta
        active for funding_overlay_ttl_days or until next rebalance
```

Parametros iniciales:

| Parametro | Grid |
|---|---|
| `use_funding_overlay` | false/true |
| `funding_source` | bybit_perp, okx_swap si disponible |
| `funding_low_pctile` | 0.05, 0.10 |
| `funding_high_pctile` | 0.90, 0.95 |
| `funding_overlay_delta` | 0.03, 0.05, 0.10 |
| `funding_overlay_ttl_days` | 3, 7, 14 |
| `funding_dedup_days` | 7, 14 |
| `funding_overlay_phases` | all, bear_onset+accumulation, accumulation |

Reglas de seguridad:

- usar solo settlements ya cerrados;
- no usar el funding de la barra actual;
- deduplicar señales solapadas;
- reportar impacto separado: retorno por overlay, coste extra, rebalanceos añadidos.

### H3 — Degradation/Chop Diagnostics, no Q4 overfit

[Certain] Q4 2025 ya fue analizado y muchas mitigaciones quedaron descartadas. No reabrir
`cooldown=7d`, ADX gate o cap sobre bear_onset solo para arreglar ese tramo.

[Likely] Lo que si merece v6 es un diagnostico formal de degradacion:

- frecuencia de rebalanceos por fase vs historico;
- flips de target 0.20/0.30/0.60/0.80/1.00 por mes;
- coste por churn;
- divergencia target vs despues;
- contribucion por fase y ciclo.

Solo si el diagnostico encuentra un patron repetido en varios ciclos se permite un candidato de
chop guard.

Parametros si llega a testearse:

| Parametro | Grid minimo |
|---|---|
| `use_chop_guard` | false/true |
| `chop_lookback_days` | 30, 60 |
| `chop_min_regime_flips` | 2, 3 |
| `chop_extra_rebalance_threshold` | +0.05, +0.10 |
| `chop_phases` | bull_peak, bear_onset, bull_peak+bear_onset |

Gate duro: si solo mejora Q4 2025, `REJECT`.

### H4 — Rolling Start / Phase Start Validation

[Certain] PropSwing demostro que la fecha de inicio cambia la conclusion. v6 necesita matrices de
inicio como parte del protocolo, no solo backtests 2015 y 2018.

Herramienta propuesta:

```bash
python tools/swing_rolling_start_matrix.py \
  --strategy swing \
  --from 2015-01-01 \
  --to 2026-01-01 \
  --start-every-days 30 \
  --costs realistic \
  --config '{}'
```

Salida minima:

- start_date;
- start_phase;
- candle_count;
- final_balance;
- CAGR;
- Max DD;
- rebalances;
- final_btc_qty;
- bnh_initial_btc;
- btc_vs_bnh_ratio;
- verdict vs v5 same start.

---

## 4. Estructura tecnica propuesta

### 4.1 Sin tocar default

Todo nuevo debe entrar detras de flags default `False`. v5 debe seguir siendo default y reproducible.

Flags candidatos:

```python
use_phase_policy_router: bool = False
phase_policy_profile: str = "v5_equiv"

use_funding_overlay: bool = False
funding_low_pctile: float = 0.05
funding_high_pctile: float = 0.95
funding_overlay_delta: float = 0.05
funding_overlay_ttl_days: int = 7
funding_dedup_days: int = 7
funding_overlay_phases: str = "bear_onset,accumulation"

use_chop_guard: bool = False
chop_lookback_days: int = 60
chop_min_regime_flips: int = 3
chop_extra_rebalance_threshold: float = 0.05
chop_phases: str = "bull_peak,bear_onset"
```

### 4.2 PhasePolicy

Opcion preferida para evitar mas flags ad hoc:

```python
@dataclass(frozen=True)
class PhasePolicy:
    phase: str
    neutral_target: float
    bull_target: float
    bear_target: float
    ema50_loss_cap: float | None = None
    suppress_bull: bool = False
```

`phase_policy_profile="v5_equiv"` carga una tabla constante. Cualquier perfil nuevo debe vivir en
un dict documentado, no en ifs dispersos.

### 4.3 FundingOverlayState

Estado necesario para no mirar futuro ni duplicar señales:

```python
{
  "last_funding_signal_day": "YYYY-MM-DD",
  "active_until": "YYYY-MM-DD",
  "active_delta": 0.05,
  "active_reason": "funding_p05"
}
```

Backtest y live deben usar la misma semantica. Si la señal no puede reconstruirse live, no entra.

---

## 5. Pruebas y orden de trabajo

### Fase 0 — No codigo de estrategia

1. Congelar v5 actual como baseline reproducible.
2. Exportar atribucion v5 por fase/ciclo.
3. Confirmar que los datos de funding usados por PropSwing estan disponibles con timestamp cerrado.
4. Añadir tests de herramientas, no de estrategia.

Entregables:

- `tools/swing_phase_attribution.py`
- `data/runtime/swing_v5_phase_attribution.csv`

### Fase 1 — Tooling de validacion v6

Herramientas:

```text
tools/swing_phase_attribution.py
tools/swing_rolling_start_matrix.py
tools/swing_funding_overlay_screen.py
tools/swing_candidate_matrix.py
```

Tests obligatorios:

- mismo conteo de velas para baseline/candidato;
- `v5_equiv` reproduce v5 exacto;
- funding screen deduplica señales solapadas;
- phase shifts `default`, `shift_minus_30`, `shift_plus_30`, `shift_minus_60`, `shift_plus_60`.

### Fase 2 — Implementacion aislada

Orden:

1. Implementar `use_phase_policy_router` con perfil `v5_equiv`.
2. Test de paridad exacta vs v5.
3. Implementar funding overlay.
4. Implementar chop diagnostics solo como reporting.
5. No implementar chop guard hasta tener evidencia multi-ciclo.

### Fase 3 — Matriz de backtests

Cada candidato se mide contra v5 en las mismas ventanas/costes:

| Run | Ventana | Costes | Obligatorio |
|---|---|---:|---|
| A | 2015-01-01 -> 2026-01-01 | realistic | si |
| B | 2018-01-01 -> 2026-01-01 | realistic | si |
| C | 2015-01-01 -> 2026-01-01 | conservative | finalistas |
| D | 2015-01-01 -> 2026-01-01 | realistic + phase shifts | finalistas |
| E | rolling starts cada 30d | realistic | finalistas |
| F | paper/OOS posterior a 2026-01-01 | real/paper | requisito de adopcion |

Formato de tabla:

| Config | Window | Cost | Candles | Final | CAGR | Max DD | Rebalances | final_btc_qty | btc_vs_bnh_ratio | Verdict |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|

Veredictos permitidos:

- `ADOPT`: solo si mejora OOS/forward y no empeora anclas.
- `REJECT`: falla una ventana, reduce mucho BTC acumulado, o mejora solo un tramo.
- `NEEDS_MORE_VALIDATION`: mejora backtest cerrado pero no tiene OOS suficiente.

### Fase 4 — Criterios de promocion

Un v6 candidato debe cumplir todo:

1. `v5_equiv` exacto antes de medir variantes.
2. No empeora CAGR v5 por mas de 0.5pp en 2015 realistic.
3. No empeora Max DD v5 por mas de 1.0pp en 2015 realistic.
4. No reduce `btc_vs_bnh_ratio` por debajo de v5 en mas de 0.03 absoluto.
5. No añade mas de 20% de rebalanceos frente a v5 salvo mejora clara de BTC acumulado.
6. No depende de una sola mejora de Q4 2025.
7. Sobrevive a phase shift +/-60d sin colapso de CAGR/DD.
8. Tiene evidencia forward/paper posterior a 2026-01-01.

---

## 6. Matriz inicial de candidatos

| ID | Config base | Cambio | Prioridad | Resultado esperado | Estado |
|---|---|---|---:|---|---|
| V6-0 | v5 | Ninguno; baseline | P0 | Reproducir anclas | pendiente |
| V6-1 | v5 | `use_phase_policy_router=true`, `v5_equiv` | P0 | Paridad exacta | pendiente |
| V6-2 | V6-1 | Funding overlay +0.05, ttl 7d, phases bear+accum | P1 | Mejor recompra sin exceso de churn | pendiente |
| V6-3 | V6-1 | Funding overlay +0.10, ttl 7d | P2 | Variante agresiva | pendiente |
| V6-4 | V6-1 | Accumulation bear target 0.30/0.35 | P2 | Mas USDT si bear persiste | pendiente |
| V6-5 | V6-1 | Bull peak neutral 0.75 | P3 | Menor exposicion tarde-ciclo | pendiente |
| V6-6 | V6-1 | Chop guard reporting only | P1 | Diagnostico, no alpha | pendiente |

No testear de entrada:

- `min_btc_pct=0.0`: ya descartado como default por BTC final.
- caps globales de `max_btc_pct`: descartados, matan CAGR.
- latch del bull peak cap: descartado.
- suprimir todo regime en bear_onset: descartado.
- shorts o perps dentro de Swing: fuera de tesis.

---

## 7. Comandos propuestos

Baseline:

```bash
python main.py backtest --strategy swing --from 2015-01-01 --to 2026-01-01 --costs realistic
python main.py backtest --strategy swing --from 2018-01-01 --to 2026-01-01 --costs realistic
```

Paridad v5-equivalent:

```bash
python main.py backtest --strategy swing --from 2015-01-01 --to 2026-01-01 --costs realistic \
  --config '{"use_phase_policy_router": true, "phase_policy_profile": "v5_equiv"}'
```

Funding overlay candidato:

```bash
python main.py backtest --strategy swing --from 2015-01-01 --to 2026-01-01 --costs realistic \
  --config '{"use_phase_policy_router": true, "phase_policy_profile": "v5_equiv", "use_funding_overlay": true, "funding_overlay_delta": 0.05, "funding_overlay_ttl_days": 7, "funding_overlay_phases": "bear_onset,accumulation"}'
```

Sensitivity de calendario:

```bash
python tools/sens_phases.py --strategy swing --config '{"use_funding_overlay": true}'
```

Rolling starts:

```bash
python tools/swing_rolling_start_matrix.py --start-every-days 30 --costs realistic
```

---

## 8. Riesgos principales

1. **Overfit invisible:** funding overlay puede mejorar solo por 2024-2025. Requiere desglose por
   ciclos y rolling starts.
2. **Mas churn:** cualquier overlay que aumente rebalanceos puede perder edge por costes.
3. **Menos BTC final:** si mejora USDT pero reduce `btc_vs_bnh_ratio`, no sirve para la tesis del
   usuario.
4. **Datos no reproducibles:** funding de perps debe cachearse y fecharse igual en backtest/live.
5. **Confundir prop con spot:** v6 no debe heredar shorts, leverage, stops de challenge ni targets
   de profit mensuales.

---

## 9. Decision recomendada

[Likely] Si merece explorar v6, pero solo como plan despues de cerrar el primer tramo de paper v5.
La prioridad inmediata sigue siendo validar v5 forward: F13, F15 y F19. Mientras tanto, se puede
avanzar en tooling de v6 porque no toca el default.

Orden recomendado:

1. Crear atribucion v5 por fase/ciclo.
2. Crear rolling-start matrix.
3. Crear funding overlay screen con dedup.
4. Implementar `phase_policy_router` en modo `v5_equiv`.
5. Solo despues implementar candidatos V6-2/V6-4.

Primer posible hito de decision:

```text
Si funding overlay +0.05 en bear_onset/accumulation:
- no empeora 2015/2018/conservative,
- mantiene btc_vs_bnh_ratio,
- no añade >20% rebalanceos,
- mejora OOS/paper 2026+,
entonces pasa a NEEDS_MORE_VALIDATION como v6 candidate.
```

Hasta que exista evidencia forward, ningun candidato v6 debe marcarse `ADOPT`.
