---
description: Validar integridad de datos OHLCV (descarga, cache, API)
argument-hint: [symbol] [bar] [ventana]
---

Valida la integridad de los datos: $ARGUMENTS

Comprueba:
1. **Determinismo:** corre la misma ventana dos veces y confirma velas analizadas IDENTICAS.
   Si difieren -> el cache o la paginacion estan rotos (historico: una pagina OKX = 300 velas
   perdidas en silencio). Ver commit 12f8630.
2. **Cache (`data/cache/{symbol}_{bar}.json`):**
   - `complete: true` (descargas truncadas no se cachean).
   - `range_from_ms`/`range_to_ms` cubren la ventana pedida (con warmup: Swing 250d, Pro Trend 625d).
   - Nº de velas coherente con el rango (1H: ~8760/año).
   - Para forzar re-descarga limpia: borrar el archivo.
3. **Continuidad:** usa `contiguity_report` — huecos > 3 velas se avisan. Distingue outage real de
   exchange (aceptable) de descarga incompleta (bug).
4. **Fuentes/fallback:** OKX principal, Binance si OKX vacio, Bitstamp para gap pre-2017 (BTC 2015-16).
   Bitstamp trata USD como USDT. Confirma que el merge deduplica por timestamp.
5. **Fragilidad del punto de inicio:** el resultado varia segun donde arranca el historico
   (leccion historica: 97105 velas de relleno PARCIAL -> PF 2.40 vs 96906 -> 4.33). El canonico
   actual (2026-07-02) = 102931 velas, relleno COMPLETO/continuo (cero huecos >24h) -> PF 4.43.
   Si auditas, mide inicio 2015 vs 2016 vs 2017 y confirma PF como rango, no ancla.
6. **API viva:** si algo falla, ¿degrada en silencio? (market_context/macro_context lo hacen). Reporta
   si un contexto externo esta devolviendo defaults en vez de datos reales.

Reporta OK o los problemas concretos con evidencia (conteos, timestamps, rangos).
