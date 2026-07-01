---
description: Comparar candidato vs baseline v1 anclado, sin mezclar metricas
argument-hint: <journal o resultado del candidato>
---

Compara el candidato contra el **baseline v1 ANCLADO** sin mezclar metricas: $ARGUMENTS

**Baseline v1 (dataset canonico 96906 velas, BTC 2015-2026 realistic):**
- CAGR +78.4% | PF 4.33 | Max DD -57.60% | 65 trades | Q4 2025 -$129,784
- 2018-2026: +36.7% CAGR aprox (referencia secundaria)

Reglas de comparacion honesta:
1. **Mismo dataset.** Confirma que candidato y baseline tienen el MISMO numero de velas
   analizadas. Si difieren, la comparacion es invalida (bug de datos, no de estrategia) — ver /data-check.
2. **Mismos costes y misma ventana.** No compares realistic vs ideal, ni 2015 vs 2018.
3. **Tabla por metrica, no promedios.** Muestra CAGR, PF, Max DD, trades y Q4 2025 en columnas
   separadas. Un CAGR mayor con PF peor NO es "mejor" — dilo explicito.
4. **Criterio go/no-go (SESSION.md):** solo adopta como default si mantiene o mejora 2015-2026
   Y no rompe 2018-2026, con PF/DD no materialmente peores. Si solo mejora por eliminar 1 trade
   perdedor, es overfitting salvo que ETH/walk-forward lo confirmen.
5. **Da un veredicto claro:** ADOPTAR / DESCARTAR / NECESITA WALK-FORWARD. Sin ambiguedad.

Recuerda: el resultado es sensible al punto de inicio (97105 velas daban PF 2.40). Reproducibilidad != correccion.
