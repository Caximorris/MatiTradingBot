---
description: Auditar un backtest en busca de sesgos (lookahead, leakage, costes, timezone, gaps)
argument-hint: [estrategia o archivo a auditar]
---

Audita en busca de sesgos que inflen el resultado: $ARGUMENTS

Revisa CADA punto y reporta hallazgos con severidad (CRITICO/ALTO/MEDIO/BAJO) y file:line:

1. **Lookahead bias** (tolerancia cero, ver SESSION.md reglas invariantes):
   - Datos diarios/semanales/4H usados intradia deben estar CERRADOS antes del tick.
   - MVRV = dia anterior. VIX/DXY/NDX = sesion anterior. Funding = dia completo anterior.
   - Bloque 4H actual incompleto NO se usa. Semana en curso NO cuenta para weekly_trend.
   - Verifica los offsets en macro_context/market_context/funding_context/pro_trend.
2. **Leakage:** ningun indicador usa datos futuros via resample, shift negativo, o warmup mal cortado.
   Confirma que warmup_bars se excluyen de la simulacion (timestamp < from_ts).
3. **Costes:** fee 0.1% aplicado en cada fill. Modo declarado (ideal/realistic/conservative) coincide
   con lo usado. No hay trades "gratis".
4. **Slippage:** aplicado segun modo (0/5/15 bps). Buffer de saldo suficiente en rebalanceos grandes
   (Swing usa 0.35%). Comprueba que no se ejecuta a precio ideal.
5. **Timezone:** DB/calculos en UTC. Conversion a Europe/Madrid SOLO en reporting. Halving/sesiones
   en la TZ correcta.
6. **Gaps de datos:** huecos reales de exchange no cuentan como señales. El cache reporta huecos —
   revisa `contiguity_report`. Datos no deterministas = /data-check.
7. **Overfitting:** thresholds justificados estructuralmente, no por eliminar 1 trade. Base estadistica
   (n trades) suficiente. Concentracion de profit (¿3 trades = 90%?).

Se escèptico. Si no encuentras nada, dilo, pero primero busca de verdad.
