---
description: Implementar UNA sola hipotesis de estrategia, aislada y reversible
argument-hint: <hipotesis en una frase>
---

Vas a implementar UNA sola hipotesis: **$ARGUMENTS**

Reglas obligatorias (protocolo anti-overfitting de este proyecto, ver SESSION.md):

1. **Una hipotesis, un cambio.** Si la idea implica varios parametros, para y pregunta cual
   probar primero. Nunca combines cambios en el mismo experimento.
2. **Default preservado.** El cambio va detras de un flag/parametro de config cuyo valor por
   defecto reproduce EXACTAMENTE el comportamiento actual (v1 Swing / v13 Pro Trend). Verifica
   que `git diff` no altera el default.
3. **Reversible.** Debe poder desactivarse por `--config` o revertirse trivialmente.
4. **No tocar Pro Trend** (`strategies/pro_trend.py`) — esta pausado hasta paper trading.
   Foco actual: Swing Allocator.
5. **Serializacion:** si anades un parametro a un dataclass de config, confirma que se
   propaga por `--config` (Swing usa reflexion generica en `from_dict`, OK; Pro Trend NO).
6. **Escribe la hipotesis y el mecanismo causal esperado** antes de codificar. Si no puedes
   articular POR QUE deberia funcionar estructuralmente, no es una hipotesis, es fitting.

Al terminar: muestra el diff, el comando de test exacto (usa /run-backtest) y NO lo declares
validado hasta correrlo y pasar por /compare-results contra el baseline anclado.
