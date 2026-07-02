---
description: Comparar candidato vs baseline v1 anclado, sin mezclar metricas
argument-hint: <journal o resultado del candidato>
---

Compara el candidato contra el **baseline v1 ANCLADO** sin mezclar metricas: $ARGUMENTS

**Baseline v4 ANCLADO — DEFAULT actual (dataset canonico 102931 velas / 96930 analizadas, BTC 2015-2026 realistic):**
- CAGR +86.2% | Max DD -52.71% | PF 4.43 | 68 trades | Calmar 1.63 | Sharpe 1.38 | Sortino 1.57
- 2018-2026: +47.6% CAGR / Max DD -53.42% (referencia secundaria)
- v4 = v3 + `min_btc_pct=0.20` + `delta_bear_onset=-0.30`. Rollback v3: `{"min_btc_pct":0.30,"delta_bear_onset":-0.20}`.
- RECORDAR: anclas de comparacion = CAGR y Max DD (estables). PF es FRAGIL al punto de inicio, usar como rango.

Reglas de comparacion honesta:
1. **Mismo dataset.** Confirma que candidato y baseline tienen el MISMO numero de velas
   analizadas. Si difieren, la comparacion es invalida (bug de datos, no de estrategia) — ver /data-check.
2. **Mismos costes y misma ventana.** No compares realistic vs ideal, ni 2015 vs 2018.
3. **Tabla por metrica, no promedios.** Muestra CAGR, PF, Max DD, trades y Q4 2025 en columnas
   separadas. Un CAGR mayor con PF peor NO es "mejor" — dilo explicito.
   **Anclas estables = CAGR y Max DD** (test de fragilidad sesion 13: varian solo ~3pp segun punto
   de inicio). **PF es fragil** (2.51/3.70/4.33 segun arranque 2016/2017/2015) — trata PF como rango
   orientativo, no como veredicto. No adoptes/descartes un candidato por un delta de PF si CAGR/DD no
   se mueven.
4. **Criterio go/no-go (SESSION.md):** solo adopta como default si mantiene o mejora 2015-2026
   Y no rompe 2018-2026, con PF/DD no materialmente peores. Si solo mejora por eliminar 1 trade
   perdedor, es overfitting salvo que ETH/walk-forward lo confirmen.
5. **Da un veredicto claro:** ADOPTAR / DESCARTAR / NECESITA WALK-FORWARD. Sin ambiguedad.

Recuerda: el resultado es sensible al punto de inicio (leccion historica: 97105 velas de relleno parcial daban PF 2.40 vs 96906 → 4.33; el canonico 102931 continuo da 4.43). Reproducibilidad != correccion.
