---
description: Resumen compacto de un journal de backtest sin leer el JSON crudo (ahorro de tokens)
---

Los journals (`backtests/journal_*.json`) pueden pesar hasta ~10 MB. **Nunca** hagas `Read` del JSON
crudo — el hook `read_guard.py` lo bloquea por diseño. Usa el extractor:

```bash
python tools/journal_summary.py <ruta-al-journal>       # summary de uno concreto
python tools/journal_summary.py --latest swing          # el journal mas reciente que matchee "swing"
python tools/journal_summary.py --latest pro_trend      # idem para pro_trend
python tools/journal_summary.py --trades <ruta>         # summary + una linea por trade/rebalanceo
```

Devuelve solo lo que importa para revisar un backtest: `meta` (estrategia, ventana, costes,
`resolved_config`), `meta.backtest` (balance, CAGR, Max DD, PF, Sharpe, trades) y `statistics`.
Salida tipica: unos cientos de tokens en vez de millones.

Si necesitas UN campo especifico de un journal, usa `jq` o `Grep` sobre el archivo en vez de cargarlo entero.

Argumentos recibidos: $ARGUMENTS
Si el usuario paso un token (p.ej. `swing`, `pro_trend`, o una ruta), ejecuta el comando adecuado y
reporta los numeros clave: CAGR, Max DD, PF, trades y (si es Swing) `btc_vs_bnh_ratio`.
