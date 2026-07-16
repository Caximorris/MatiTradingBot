# Swing Allocator v6 — Plan de Investigacion desde PropSwing/CFT

**Fecha:** 2026-07-05  
**Estado:** ADOPTADO y CONGELADO como default (decision explicita 2026-07-13).
**Baseline de rollback:** Swing Allocator v5 post-audit.
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

[Certain] La ventana 2015-2026 sigue cerrada para nuevas optimizaciones. V6-2 fue promovido como
excepcion explicita y acotada: v5/v6 iniciaron paper simultaneamente, v6 paso todas las pruebas
disponibles y el cambio solo selecciona el default paper; no autoriza live. Cualquier sucesor debe:

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

Veredicto inicial (2026-07-05): `NEEDS_MORE_VALIDATION`. Superado por la decision final de 2026-07-13.

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
| `funding_overlay_source` | `bybit` (investigacion historica) o `okx` (paper forward) |
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

### 4.1 Default y rollback

V6-2 usa ambos flags `True` por defecto. V5 debe seguir reproducible con ambos `False`; cualquier
componente posterior a v6 debe entrar detras de un flag nuevo default `False`.

Flags candidatos:

```python
use_phase_policy_router: bool = True
phase_policy_profile: str = "v5_equiv"

use_funding_overlay: bool = True
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
8. Tiene evidencia forward/paper posterior a 2026-01-01. Excepcion consumida: V6-2 por decision
   explicita del usuario; no reutilizar para V7 ni para ajustar thresholds sobre muestra cerrada.

---

## 6. Matriz inicial de candidatos

| ID | Config base | Cambio | Prioridad | Resultado esperado | Estado |
|---|---|---|---:|---|---|
| V6-0 | v5 | Ninguno; baseline | P0 | Reproducir anclas | ejecutado |
| V6-1 | v5 | `use_phase_policy_router=true`, `v5_equiv` | P0 | Paridad exacta | ejecutado; paridad exacta |
| V6-2 | V6-1 | Funding overlay +0.05, ttl 7d, phases accumulation, p10/p90 | P1 | Mejor recompra sin exceso de churn | ADOPTADO; DEFAULT CONGELADO |
| V6-3 | V6-1 | Funding overlay +0.10, ttl 7d, phases accumulation, p10/p90 | P2 | Variante agresiva | REJECT como default: exceso de churn |
| V6-4 | V6-1 | Accumulation bear target 0.30/0.35 | P2 | Mas USDT si bear persiste | pendiente |
| V6-5 | V6-1 | Bull peak neutral 0.75 | P3 | Menor exposicion tarde-ciclo | pendiente |
| V6-6 | V6-1 | Chop guard reporting only | P1 | Diagnostico, no alpha | pendiente |

No testear de entrada:

- `min_btc_pct=0.0`: ya descartado como default por BTC final.
- caps globales de `max_btc_pct`: descartados, matan CAGR.
- latch del bull peak cap: descartado.
- suprimir todo regime en bear_onset: descartado.
- shorts o perps dentro de Swing: fuera de tesis.

### Ejecucion 2026-07-06

Screen de funding:

- `bear_onset,accumulation` no queda limpio: `funding_high` en `bear_onset` sale negativo a 7d.
- `accumulation` queda vivo en p05/p95 y p10/p90; p10/p90 da mas muestra y mejor resultado.

Anclas V6-2 p10/p90, `funding_overlay_delta=0.05`, `ttl=7d`, `phases=accumulation`:

| Ventana | Coste | v5 final | v6 final | CAGR v5/v6 | Max DD v5/v6 | Rebalances v5/v6 | ACB trades v5/v6 | BTC ratio v5/v6 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 2015-2026 | realistic | $9.138M | $9.505M | 85.84 / 86.51 | 52.73 / 52.73 | 136 / 136 | 70 / 70 | 0.8171 / 0.8499 |
| 2018-2026 | realistic | $219.8k | $229.0k | 47.14 / 47.90 | 53.72 / 53.72 | 103 / 103 | 53 / 53 | 0.8432 / 0.8785 |
| 2015-2026 | conservative | $8.897M | $9.255M | 85.40 / 86.06 | 52.88 / 52.88 | 136 / 136 | 70 / 70 | 0.7961 / 0.8281 |

Rolling starts anuales 2018-2024:

- `+0.05`: 8/8 `NEEDS_MORE_VALIDATION`, sin `REJECT`; mejora final y BTC ratio en 7/8, sin efecto en el start 2024-12-30.
- `+0.10`: mejora final, pero da `REJECT` en 4/8 por exceder el limite de churn (>20% rebalanceos).

Decision final: V6-2 p10/p90 `+0.05` es el default congelado. V6-3 `+0.10` queda rechazado
como default por exceso de churn.

### Revalidacion 2026-07-13

V5 y V6-2 se reejecutaron emparejados sobre las mismas velas del cache canonico (102931 filas
OHLCV) y un cache Bybit reconstruido con 6904 settlements hasta 2026-07-13 16:00 UTC. Los tres
anchors reprodujeron las cifras anteriores:

- 2015-2026 realistic, 96907 velas de test: v5 $9.137M / 85.84% / -52.73% / 0.8171 BTC ratio;
  v6 $9.505M / 86.51% / -52.73% / 0.8499.
- 2018-2026 realistic, 70129 velas de test: v5 $219.8k / 47.14% / -53.72% / 0.8432;
  v6 $229.0k / 47.90% / -53.72% / 0.8785.
- 2015-2026 conservative, 96907 velas de test: v5 $8.897M / 85.40% / -52.88% / 0.7961;
  v6 $9.255M / 86.06% / -52.88% / 0.8281.

Ambas configuraciones mantuvieron el mismo churn (136 eventos; 70 ACB trades en 2015 y 103/53
en 2018). V6-2 mejora las tres anclas y 7/8 rolling starts sin empeorar DD, churn ni BTC acumulado.
El usuario aprobo reemplazar v5 porque ambos iniciaron paper al mismo tiempo y no existe ventaja
forward previa de v5 que proteger. Veredicto: `ADOPT`; v6-2 queda congelado como default y v5 se
mantiene como control/rollback. Durante `bear_onset` siguen siendo equivalentes.

### Correccion de comparabilidad (2026-07-16)

La revalidacion anterior es un ancla historica protegida, no una licencia para reconstruir o
sobrescribir sus inputs. Una corrida solo puede declararse comparable con el ancla v6-2 si conserva
el contenido, orden y duplicados OHLCV; ventana y warmup; harness, rellenos y costes; configuracion
resuelta; y snapshot Bybit de funding identificado por hash, cobertura y slice consumido. Compartir
un rango de fechas no prueba paridad.

El cache local Bybit SHA-256
`23cc1952a9eed3806fb6f91e9cfdd788d0ae1dcfcc244524ea3f904b4497685f` no reproduce el input de
overlay protegido. La corrida local de $9,532,749.59 usa semantica de fin distinta: esta
**supersedida como control exacto** y no puede llamarse control funding-off/v5-compatible protegido
sin manifest valido. El control funding-off/v5-compatible exacto es $9,137,545.81; el ancla
funding-on v6-2 de corte midnight protegida es $9,505,067.92. No debe atribuirse la diferencia al
motor ni usarla para promocionar, rechazar o recalibrar v6-2.

La compatibilidad exacta con v5 tiene dos significados distintos:

- El rollback de v5 es `use_phase_policy_router=false` y `use_funding_overlay=false`.
- V6-1 con `phase_policy_profile=v5_equiv` y overlay desactivado debe reproducir v5 con inputs y
  ejecucion identicos. V6-2 no tiene por que reproducir v5 en `accumulation`, porque su overlay
  puede actuar alli; durante `bear_onset` permanece equivalente.

Las 474 filas OHLCV identicas del empalme de 2017 son un defecto material conocido, no una correccion
aplicada: el validador las reporta, pero nunca reescribe el cache canonico. Permanecen dentro de la
identidad del dataset y deben coincidir, junto con el fingerprint/version, antes de comparar P&L,
CAGR, drawdown o rebalanceos. Ningun resultado que use una copia deduplicada, reordenada o con otra
cobertura es comparable con estas anclas.

Con el overlay habilitado, un snapshot de funding ausente, vacio, malformado o stale aborta la
corrida con un error accionable; no se degrada silenciosamente a funding neutral ni a v5. La falta
previa a cotizacion solo es neutral con evidencia inmutable de listing/inicio; el primer settlement
no prueba cobertura. El ancla v6-2 no puede re-certificarse hoy sin el input Bybit protegido exacto.

### Fuente forward OKX (2026-07-16)

El fleet paper y el bot OKX Demo fijan `funding_overlay_source="okx"` y consumen el snapshot local
`funding_okx_BTC-USDT-SWAP.json`, actualizado atómicamente desde el endpoint público de settlements
finales de OKX. Esto elimina la dependencia operativa de Bybit en la VM de EE. UU.; el refresco no
se ejecuta dentro de un backtest ni reescribe el input Bybit protegido. La API pública de OKX sólo
expone una ventana histórica corta, por lo que esta es una variante **forward-only**: no sustituye
el snapshot Bybit ni certifica paridad histórica con el ancla v6-2. Si falta o queda stale el
snapshot OKX, una configuración con overlay habilitado falla cerrada; el rollback explícito v5
sigue siendo desactivar el overlay por configuración.
Las estrategias que no consumen funding no lo cargan.

---

## 7. Comandos propuestos

Default v6:

```bash
python main.py backtest --strategy swing --from 2015-01-01 --to 2026-01-01 --costs realistic
python main.py backtest --strategy swing --from 2018-01-01 --to 2026-01-01 --costs realistic
```

Rollback v5:

```bash
python main.py backtest --strategy swing --from 2015-01-01 --to 2026-01-01 --costs realistic \
  --config '{"use_phase_policy_router": false, "use_funding_overlay": false}'
```

Funding overlay candidato:

```bash
python main.py backtest --strategy swing --from 2015-01-01 --to 2026-01-01 --costs realistic \
  --config '{"use_phase_policy_router": true, "phase_policy_profile": "v5_equiv", "use_funding_overlay": true, "funding_overlay_delta": 0.05, "funding_overlay_ttl_days": 7, "funding_overlay_phases": "accumulation", "funding_low_pctile": 0.10, "funding_high_pctile": 0.90}'
```

Sensitivity de calendario:

```bash
python tools/sens_phases.py --strategy swing --config '{"use_funding_overlay": true}'
```

Rolling starts:

```bash
python tools/swing_rolling_start_matrix.py --start-every-days 30 --costs realistic
```

Paper aislado (para una instalación nueva; la VM existente usa el reconciliador de fleet):

```bash
python tools/swing_paper_setup.py --enable
```

Esto registra `swing_allocator_v6_btc_usdt` con `instance_id=v6` y
`paper_portfolio_id=swing_v6`. No registrar legacy/v5 como parte de la fleet operativa; si se
necesita el rollback, conservar su wallet/journal histórico y activarlo solo de forma explícita:

```bash
python tools/swing_paper_setup.py --include-v5 --enable
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

## 9. Decision

[Certain] V6-2 fue adoptado y congelado como default por decision explicita del usuario el
2026-07-13. V5 sigue aislado como control y rollback. La prioridad inmediata es asegurar frescura
del funding en la VM antes de `accumulation` y continuar F13/F15/F19.

Orden recomendado:

1. Crear atribucion v5 por fase/ciclo.
2. Crear rolling-start matrix.
3. Crear funding overlay screen con dedup.
4. Implementar `phase_policy_router` en modo `v5_equiv`.
5. Solo despues implementar candidatos V6-2/V6-4.

Primer posible hito de decision:

```text
Si funding overlay +0.05 en accumulation p10/p90:
- no empeora 2015/2018/conservative,
- mantiene btc_vs_bnh_ratio,
- no añade >20% rebalanceos,
- mejora OOS/paper 2026+,
entonces pasa a ADOPT solo bajo la excepcion explicita documentada del 2026-07-13.
```

No ajustar mas thresholds ni promover un sucesor de v6 sin evidencia forward diferenciada.
