# BTC Swing Allocator — Plan de Diseño

**Fecha: 2026-06-30**
**Estado: PLANNING — no tocar Pro Trend v13**
**Objetivo: Batir BTC Buy & Hold en retorno absoluto con DCA mensual**

---

## 1. Por qué Pro Trend no puede cumplir este objetivo

Pro Trend fue diseñado para reducir riesgo, no para maximizar retorno. Sus características
estructurales lo limitan contra B&H:

- 65% del tiempo en USDT → pierde compounding en bull markets
- 1-3 trades/año → pocas oportunidades de añadir alpha
- Objective: supervivencia de capital → incompatible con "maximizar e ignorar caídas"

**El usuario que acepta caídas y tiene horizonte de años NO necesita un bot de gestión de riesgo.
Necesita un bot que acumule más BTC del que tendría con B&H.**

---

## 2. Concepto central — lo que cambia radicalmente

### Pro Trend: todo o nada
```
Estado A: 100% USDT (esperando)
Estado B: 80-90% invertido en BTC
Transición: 1-3 veces al año
```

### BTC Swing Allocator: gestión de porcentaje
```
Estado mínimo: 40% BTC siempre (nunca a cero)
Estado normal: 60-70% BTC
Estado agresivo: 90-100% BTC en bull confirmado
Transición: 8-15 veces al año
```

**La diferencia filosófica:** no salir de BTC, sino ajustar cuánto BTC tienes.
Vender en subidas, comprar en correcciones. Acumular más BTC que B&H a lo largo del tiempo.

### Por qué esto puede batir B&H sin apalancamiento

BTC tiene correcciones regulares del 15-40% incluso en bull markets.
Si vendes el 30% de tu posición en cada pico parcial y recompras en la corrección:

```
Ejemplo:
- Inicio: 1 BTC a $40k
- Señal de sobrecompra: vende 0.3 BTC a $60k → tienes 0.7 BTC + $18k USDT
- Corrección: BTC baja a $45k
- Recompra: $18k compra 0.4 BTC → tienes 1.1 BTC
- Net: +0.1 BTC vs B&H que sigue en 1 BTC
- Repetir en cada ciclo → acumulación de BTC
```

Este mecanismo NO requiere predecir tops exactos. Solo necesita que las señales
apunten en la dirección correcta más veces de las que se equivocan.

---

## 3. Constraint de costes — lo más importante

Con costes realistic (0.1% fee + 5bps slippage = ~0.15% por lado):

| Trades/año | Coste fee anual | Necesitas generar sobre B&H |
|-----------|----------------|------------------------------|
| 8         | ~2.4%          | >2.4% anual                  |
| 15        | ~4.5%          | >4.5% anual                  |
| 24        | ~7.2%          | >7.2% anual                  |
| 50+       | >15%           | Imposible sistemáticamente   |

**Conclusión: target 8-15 rebalanceos al año. Ni más ni menos.**
Por encima de 20, el coste mata el edge. Por debajo de 6, nos parecemos demasiado a Pro Trend.

---

## 4. Lo que sabemos que funciona (de Pro Trend)

Llevar al nuevo bot — evidencia directa de backtests 2015-2026:

### Señales con evidencia sólida
- **EMA50D/EMA200D cross** — el indicador más fiable de régimen macro. Golden cross = bull, death cross = bear. Todos los grandes ganadores de Pro Trend ocurrieron con golden cross activo.
- **MVRV > 2.5** — señal de sobrevaluación. Cuando MVRV supera 2.5, el riesgo de corrección grande aumenta. En Pro Trend activó correctamente en los dos picos 2021 y 2024.
- **Pi Cycle Top** — 100% win rate en salidas. Las dos veces que disparó en el backtest, BTC cayó. Útil para reducción agresiva de posición.
- **VIX > 35** — contexto macro de pánico. Históricamente coincide con oportunidades de compra (mercado sobrevende BTC con renta variable).
- **ADX > 15** — confirma tendencia activa. Sin tendencia, los swings no funcionan.
- **Halving phases** — la fase post_halving/bull_peak históricamente justifica más agresividad (sizing_ultra en Pro Trend).

### Lo que NO llevar
- **Sistema de scoring de 13+ puntos** — demasiado complejo, sobrefitteado sobre 12-20 trades.
- **MACD exit** — cortaba ganadores, desactivado en Pro Trend v8.
- **RSI divergencia alcista/bajista como signal principal** — añade ruido.
- **Cooldowns de 30 días** — para swing trading son demasiado largos, pierdes la reentrada.
- **Bear confirmed exit** — útil en Pro Trend, pero en swing allocator el "exit" es solo reducir posición, no salir.
- **Funding rate gate** — para swings de 2-4 semanas el funding tiene menos impacto.

---

## 5. Arquitectura técnica propuesta

### 5.1 Lógica de asignación

```
Función: calcular_target_allocation(datos) → float [0.30, 1.00]

Input: precio actual + indicadores

Régimen macro (peso 40%):
  - Bull (EMA50D>EMA200D + precio>EMA200D + ADX>15): +0.20 al allocation
  - Bear (EMA50D<EMA200D): -0.20 al allocation
  - Neutral: 0

Fase halving (peso 20%):
  - post_halving/bull_peak: +0.10
  - bear_onset/accumulation: -0.10

Sobrecompra/sobreventa (peso 25%):
  - RSI(14,daily) > 75: -0.15 (vender parcial en fuerza)
  - RSI(14,daily) < 35: +0.15 (comprar en debilidad)
  - MVRV > 2.5: -0.10 adicional

Señales de techo/suelo (peso 15%):
  - Pi Cycle Top activo: -0.25 (reducción agresiva)
  - VIX > 35: +0.10 (pánico = oportunidad compra)
  - VIX > 55: -0.15 (crisis sistémica, reducir)

Base: 0.60 (siempre empezar en 60% BTC)
Mínimo hard: 0.30 (nunca menos del 30% en BTC)
Máximo hard: 1.00 (máximo 100% en BTC)
```

### 5.2 Reglas de ejecución

```
- Evaluar señales cada 4H (no 1H — reduce ruido y costes)
- Solo rebalancear si |target - actual| > 0.10 (evitar microajustes caros)
- Rebalanceo mínimo: 3 días entre ajustes del mismo tipo
- Tamaño mínimo de orden: 5% del portfolio (ordenes pequeñas no compensan el fee)
- Slippage estimado: 5bps (igual que Pro Trend realistic)
```

### 5.3 DCA mensual integration

```
- Capital nuevo mensual → compra BTC si allocation actual < target
- Capital nuevo mensual → queda en USDT si allocation actual > target
- Esto convierte el DCA en un rebalanceo inteligente, no ciego
```

---

## 6. Métricas de éxito — cómo saber si funciona

El bot debe batir B&H en **todas** estas métricas, no solo en una:

| Métrica | Mínimo exigido | Por qué |
|---------|---------------|---------|
| CAGR vs B&H | +2pp mínimo | Cubrir riesgo de modelo |
| BTC acumulado vs B&H | >1.0x | Si tienes menos BTC que B&H, has perdido |
| Max DD vs B&H | Menor o igual | Si asumes más DD sin más retorno, no tiene sentido |
| Sharpe | >0.8 | Mejor que Pro Trend (0.74) |
| Peor año vs B&H | No perder más | En años bajistas, no empeorar B&H |

**Métrica nueva — BTC acumulado:** cuántos BTC tiene la estrategia al final vs cuántos
tendría el B&H. Si el bot da más USDT pero menos BTC, para un holder de largo plazo
que cree en BTC es una métrica relevante.

---

## 7. Plan de validación — orden estricto

### Paso 1: Baseline de rebalanceo mecánico (PRIMERO)
**Pregunta:** ¿El simple rebalanceo mensual 60/40 BTC/USDT bate a B&H?
Si la respuesta es NO, el concepto entero está en duda antes de añadir complejidad.

```bash
# Nuevo comando a implementar
python main.py backtest --strategy swing_allocator --mode baseline_6040 \
  --from 2015-01-01 --to 2026-01-01 --costs realistic
```

### Paso 2: Régimen macro solamente
**Pregunta:** ¿Asignar 30/60/90% basado solo en EMA50D/200D bate al baseline 60/40?

### Paso 3: Añadir MVRV
**Pregunta:** ¿El ajuste por valoración (MVRV>2.5 reduce) añade alpha neto de costes?

### Paso 4: Añadir RSI diario
**Pregunta:** ¿Vender en RSI>75 y comprar en RSI<35 añade alpha?
**Riesgo:** RSI puede estar >75 durante semanas en bull markets. Necesita cooldown.

### Paso 5: Añadir Pi Cycle + VIX
**Pregunta:** ¿Las señales extremas (tops confirmados, pánico macro) mejoran resultados?

### Paso 6: Sensitivity analysis
Solo si Paso 1-5 muestran resultado positivo. Testear:
- Allocation mínimo: 20% vs 30% vs 40% BTC
- Threshold de rebalanceo: 5% vs 10% vs 15% de diferencia
- Cooldown entre rebalanceos: 2d vs 3d vs 7d
- RSI thresholds: 70/30 vs 75/35 vs 80/25

### Paso 7: Walk-forward
Mismo protocolo que Pro Trend. Mínimo 3 ventanas independientes positivas.

### Paso 8: ETH cross-validation
Correr en ETH. Si funciona en ETH, confirma que no es overfitting de ciclos BTC.

---

## 8. Lo que puede salir mal — riesgos de diseño

### Riesgo 1: El mercado no ofrece correcciones suficientes
En bull markets de momentum (2017 Q4, 2021 Q1), BTC puede subir 200%+ sin correcciones
del >15%. El bot estaría reduciendo posición en cada RSI>75 y perdería la subida.
**Mitigación:** mínimo 40% BTC siempre, y RSI threshold alto (75, no 70).

### Riesgo 2: Costes destrozan el edge
Con 12+ rebalanceos al año, el drag acumulado puede ser mayor que el alpha generado.
**Mitigación:** umbral mínimo del 10% de diferencia antes de rebalancear.
**Test obligatorio:** comparar resultado gross (sin costes) vs net (con costes). Si el
alpha gross es <3%, el net probablemente sea negativo.

### Riesgo 3: Señales de RSI/sobrecompra en trend markets
En trend alcista fuerte, RSI puede mantenerse en zona de sobrecompra (>70) meses.
Vender en cada RSI>75 en 2021 habría sido desastroso.
**Mitigación:** RSI solo modifica allocation si también hay señal de EMA o MVRV.
Señales combinadas, no individuales.

### Riesgo 4: Lookahead bias
Los mismos 5 lookahead fixes de Pro Trend aplican aquí. Añadir desde el principio,
no como corrección posterior.

---

## 9. Implementación técnica — consideraciones

### Nuevo módulo: `strategies/swing_allocator.py`
- Independiente de Pro Trend. No tocar `pro_trend.py`.
- Hereda de `BaseStrategy` si la interfaz lo permite.
- Estado persistente: `current_btc_pct` (porcentaje actual en BTC).
- No usa el sistema de "trades" de Pro Trend — usa "rebalanceos".

### Backtest adaptado
El backtest actual calcula P&L por trades. El swing allocator necesita:
- Tracking continuo de BTC holdings + USDT holdings
- Cálculo de valor total del portfolio en cada barra
- Comparación directa contra B&H en cada punto del tiempo
- Posiblemente un módulo nuevo o extensión de `core/backtest.py`

### Journal adaptado
Registrar por evento de rebalanceo:
- Fecha/hora
- BTC% antes y después
- Precio de ejecución
- Razón del rebalanceo (qué señal lo disparó)
- Coste de la transacción
- Portfolio value antes y después

---

## 10. Cronograma sugerido

**Mientras Pro Trend v13 hace paper trading (6 meses):**

| Mes | Tarea |
|-----|-------|
| 1 | Implementar infraestructura backtest para swing allocator |
| 1-2 | Pasos 1-2 (baseline + régimen macro) |
| 2-3 | Pasos 3-4 (MVRV + RSI) |
| 3-4 | Pasos 5-6 (señales extremas + sensitivity) |
| 4-5 | Paso 7-8 (walk-forward + ETH) |
| 5-6 | Comparar resultados con Pro Trend v13 paper |
| 6+ | Decisión: lanzar swing allocator, Pro Trend, o ninguno |

---

## 11. Criterio de go/no-go

**No lanzar el swing allocator si:**
- No bate a B&H en al menos 2pp CAGR en 2015-2026
- Walk-forward falla en >1 de 3 ventanas
- El coste neto supera el alpha bruto
- ETH da resultados negativos (overfitting)
- El DD máximo es peor que B&H sin ganancia compensatoria

**Lanzar si cumple todos los criterios anteriores.**
No lanzar "porque parece prometedor" — los backtests mandan.
